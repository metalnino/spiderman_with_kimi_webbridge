"""招标文件附件抓取与正文清洗（collector/v1.2.0 tenderFile 能力，内核新模块）。

规则型 deterministic：无任何模型决策，路径死定，失败诚实返回原因，绝不造假。

各站详情路径（2026-08 实测探针，诚实记录）：
- ccgp：详情开放，HTTP 直取可拿正文；正文常带附件下载链接（PDF/DOC）→ mode=http。
- ggzy / jsggzy：detail_url 为 www.ggzy.gov.cn 的 a 页；正文在 b 页 SSR 直出
  （/information/deal/html/a/<id>.html → /information/deal/html/b/<id>.html，实测全文可读），
  附件链接在 b 页内 → mode=ggzy_http。
- chinabidding：HTTP GET 405（WAF），真浏览器可渲染正文，但招标文件下载需登录
  → mode=bridge（正文摘要可达，附件无登录时 null）。
- jiangsu_zhaobiao：HTTP 521 Cloudflare/WAF；WebBridge 真浏览器可渲染详情页，
  招标文件下载需「正式会员登录」→ mode=bridge（摘要可达，附件 null）。
- cebpub：详情页 vaptcha 人工验证码（c4.vaptcha.com），内容不渲染 → mode=blocked_vaptcha，
  不尝试、如实跳过（验证码不可绕过，登记待办）。

tenderFile 契约形状（collector/v1.2.0）：
  { "path": 下载后的文件路径（相对工作区根）,
    "text": 清洗后的正文,
    "sourceUrl": 附件原始链接（可空）,
    "format": "pdf" | "docx" | "txt"（可空） }

summary 口径：附件正文清洗后前 200 字；无附件时用详情页正文前 200 字；两者都无 → None。
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import sys
import time
import zipfile
from html import unescape
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from crawl.http_session import HttpSession  # noqa: E402
from crawl.origin import origin_lines, origin_url  # noqa: E402

TENDERFILE_DIR = ROOT / "downloads" / "tenderfiles"

# 源站 → 详情抓取模式（deterministic 路由表）
DETAIL_MODES = {
    "ccgp": "http",
    "ggzy": "ggzy_http",
    "jsggzy": "ggzy_http",
    "chinabidding": "bridge",
    "jiangsu_zhaobiao": "bridge",
    "cebpub": "bridge_vaptcha",  # vaptcha 人工一次后桥内附件可下（接口 DES 解密已实现）
    "yfbzb": "http",
    "qianlima": "bridge",  # 详情 bid-<id>.html 419 反爬，桥渲染
    "tgnet": "bridge",  # 项目详情页桥渲染
    "rccchina": "blocked_regwall",  # 注册墙（手机号+短信验证码），三级不可直取
}

# 兼容旧引用（外壳 _enrich_tenderfiles 曾按此判断 HTTP 详情源站）
HTTP_DETAIL_SOURCES = tuple(p for p, m in DETAIL_MODES.items() if m in ("http", "ggzy_http"))

# 单附件大小上限（防误下大文件）
MAX_ATTACHMENT_BYTES = 30 * 1024 * 1024
# 提取正文长度上限（防输出爆炸）
MAX_TEXT_CHARS = 200_000
# summary 长度
SUMMARY_CHARS = 200

_EXT_FORMAT = {
    "pdf": "pdf",
    "doc": "docx",
    "docx": "docx",
    "wps": "docx",
    "txt": "txt",
}

# 附件链接信号：href 内出现这些词且不在黑名单内（下载/附件/招标文件 等）
_ATTACH_WORDS = ("download", "attachment", "attach", "file", "filesource", "oss", "uuid")
_ATTACH_BLACKLIST = ("login", "register", "verify", "captcha", ".js", ".css", ".png", ".jpg", ".gif")


def _plain(html: str) -> str:
    t = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def discover_attachment_urls(html: str, base_url: str = "") -> list[tuple[str, str]]:
    """从详情页 HTML 发现招标文件附件链接，返回 [(绝对URL, format)]（去重、按 pdf>docx>txt 排序）。"""
    found: dict[str, str] = {}
    for m in re.finditer(r"<a\b[^>]*href\s*=\s*[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, flags=re.I | re.S):
        href, text = m.group(1).strip(), re.sub(r"<[^>]+>", "", m.group(2))
        low = (href + " " + text).lower()
        if any(b in low for b in _ATTACH_BLACKLIST):
            continue
        fmt = None
        path = urlparse(href).path.lower()
        for ext, f in _EXT_FORMAT.items():
            if path.endswith("." + ext) or f".{ext}?" in path:
                fmt = f
                break
        if fmt is None:
            # 非扩展名形态（servlet/download 链接）：按信号词 + 锚文本判断
            if any(w in low for w in _ATTACH_WORDS) and re.search(r"(下载|附件|招标文件|采购文件|磋商文件|询价文件|谈判文件)", text):
                fmt = "pdf"  # 未知形态默认按 pdf 尝试；下载后按魔数校验，不对会如实失败
        if fmt and href not in found:
            abs_url = urljoin(base_url, href)
            if abs_url.startswith(("http://", "https://")):
                found[href] = (abs_url, fmt)
    order = {"pdf": 0, "docx": 1, "txt": 2}
    items = sorted(found.values(), key=lambda x: order.get(x[1], 9))
    return items


def download_attachment(http: HttpSession, url: str, dest: Path, referer: str = "", cookie: str = "") -> tuple[bool, str]:
    """下载附件到 dest；返回 (ok, error)。大小超限/网络失败如实返回。"""
    try:
        headers = {}
        if referer:
            headers["Referer"] = referer
        if cookie:
            headers["Cookie"] = cookie
        _, raw, _ = http.request(url, headers=headers)
    except Exception as e:  # noqa: BLE001
        return False, f"download_failed: {str(e)[:200]}"
    if len(raw) > MAX_ATTACHMENT_BYTES:
        return False, f"download_failed: oversized {len(raw)} bytes"
    if len(raw) < 100:
        return False, f"download_failed: too small {len(raw)} bytes (likely a login/notice page)"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return True, ""


def _is_pdf_magic(b: bytes) -> bool:
    return b[:1024].lstrip().startswith(b"%PDF")


def _is_zip_magic(b: bytes) -> bool:
    return b[:4] == b"PK\x03\x04"


def _is_ole_magic(b: bytes) -> bool:
    """旧版 Word .doc（OLE2 复合文档）魔数 D0CF11E0A1B11AE1。"""
    return b[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _sniff_format(raw: bytes) -> str | None:
    """按内容魔数/编码判型（不信任 URL 扩展名）：pdf / doc / docx / txt，判不出 None。"""
    if _is_pdf_magic(raw):
        return "pdf"
    if _is_zip_magic(raw):
        return "docx"
    if _is_ole_magic(raw):
        return "doc"
    if _looks_html(raw):
        return None  # 登录页/公告页 HTML 不是附件
    for enc in ("utf-8", "gbk"):
        try:
            raw.decode(enc)
            return "txt"
        except UnicodeDecodeError:
            continue
    return None


def _looks_html(raw: bytes) -> bool:
    head = raw[:2048].lstrip().lower()
    return head.startswith((b"<!doctype html", b"<html", b"<head")) or (
        b"<script" in head and b"</" in head
    )


def extract_pdf_text(path: Path) -> str:
    import fitz  # PyMuPDF（本机已装）

    doc = fitz.open(str(path))
    try:
        parts = []
        for page in doc:
            parts.append(page.get_text("text") or "")
        return "\n".join(parts)
    finally:
        doc.close()


def extract_docx_text(path: Path) -> str:
    """docx = zip + word/document.xml，用 zipfile 直接取文本节点（无 python-docx 依赖）。"""
    with zipfile.ZipFile(str(path)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab[^>]*/>", "\t", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    return unescape(text)


def extract_doc_ole_text(path: Path) -> str:
    """旧版 Word 97-2003 .doc（OLE2）正文提取：优先分段表（piece table）解析，
    失败退「字节级正文打捞」（WPS 生成的不规范 doc 常把正文以 UTF-8/GBK 原样存流里）。

    deterministic，无外部二进制依赖；olefile 缺失时抛 RuntimeError（调用方如实失败）。
    """
    try:
        import olefile
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError("olefile not installed (legacy .doc extraction unavailable)") from e

    if not olefile.isOleFile(str(path)):
        raise RuntimeError("not an OLE file")
    ole = olefile.OleFileIO(str(path))
    try:
        stream = ole.openstream("WordDocument").read()
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"WordDocument stream missing: {str(e)[:120]}") from e
    finally:
        ole.close()

    body = _extract_doc_piece_text(stream)
    if body is None:
        body = _salvage_doc_text(stream)
    if body is None:
        raise RuntimeError("doc text extraction failed (piece table + byte salvage both empty)")
    return body


def _extract_doc_piece_text(stream: bytes) -> str | None:
    """Word 97+ 分段表解析；失败返回 None（不抛，交给打捞兜底）。"""
    if len(stream) < 0x01AC:
        return None
    fc_clx = int.from_bytes(stream[0x01A2:0x01A6], "little")
    lcb_clx = int.from_bytes(stream[0x01A6:0x01AA], "little")
    if not lcb_clx or fc_clx + lcb_clx > len(stream):
        return None
    clx = stream[fc_clx:fc_clx + lcb_clx]
    idx = clx.find(b"\x02")
    if idx == -1 or idx + 5 > len(clx):
        return None
    lcb = int.from_bytes(clx[idx + 1:idx + 5], "little")
    plc = clx[idx + 5:idx + 5 + lcb]
    if len(plc) < 12 or (len(plc) - 4) % 12 != 0:
        return None
    n = (len(plc) - 4) // 12
    out_parts: list[str] = []
    for i in range(n):
        pcd = plc[(n + 1) * 4 + i * 8:(n + 1) * 4 + i * 8 + 8]
        flags = int.from_bytes(pcd[2:4], "little")
        fc = int.from_bytes(pcd[2:6], "little") & 0x3FFFFFFF
        next_cp = int.from_bytes(plc[i * 4 + 4:i * 4 + 8], "little") if i + 1 < n else 0
        length = (next_cp - int.from_bytes(plc[i * 4:i * 4 + 4], "little")) if i + 1 < n else None
        if length is not None and length <= 0:
            continue
        if flags & 0x40000000:  # UTF-16LE 段
            start = fc * 2
            seg = stream[start:] if length is None else stream[start:start + length * 2]
            text = seg.decode("utf-16le", "ignore")
        else:  # 单字节段（中文 Word 通常为 GBK/CP936）
            seg = stream[fc:] if length is None else stream[fc:fc + length]
            try:
                text = seg.decode("gbk")
            except UnicodeDecodeError:
                text = seg.decode("gbk", "ignore")
        text = text.replace("\r", "\n").replace("\x07", "\t")
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        out_parts.append(text)
    body = "\n".join(out_parts)
    if len(re.findall(r"[\u4e00-\u9fff]", body)) < 20:
        return None
    return body


def _salvage_doc_text(stream: bytes) -> str | None:
    """字节级打捞：utf-16le（双奇偶）优先（Word/WPS 中文正文标准形态），
    其次 utf-8、最后 gbk；任何编码下中文密集文本段 >=20 字即采用。"""
    for enc, offsets in (("utf-16le", (0, 1)), ("utf-8", (0,)), ("gbk", (0,))):
        for off in offsets:
            if off >= len(stream):
                continue
            try:
                text = stream[off:].decode(enc, "ignore")
            except Exception:  # noqa: BLE001
                continue
            runs = re.findall(r"[\u4e00-\u9fffA-Za-z0-9，。、：；：（）()《》【】\-—·%￥¥.,:;!?/\\]{6,}", text)
            runs = [r.strip() for r in runs if re.search(r"[\u4e00-\u9fff]", r)]
            cjk = sum(len(re.findall(r"[\u4e00-\u9fff]", r)) for r in runs)
            if cjk >= 20:
                return "\n".join(runs)
    return None


def extract_txt_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "gbk", "gb2312"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def extract_text(path: Path, fmt: str) -> str:
    if fmt == "pdf":
        return extract_pdf_text(path)
    if fmt == "docx":
        return extract_docx_text(path)
    if fmt == "doc":
        return extract_doc_ole_text(path)
    return extract_txt_text(path)


def clean_extracted_text(text: str) -> str:
    """去页眉页脚乱码：行内高乱码率行丢弃、空白归一、长度封顶。"""
    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"[ \t\u3000]+", " ", raw_line).strip()
        if not line:
            continue
        # 乱码行：可读字符（汉字/字母/数字/标点）占比过低则丢弃
        readable = len(re.findall(r"[\u4e00-\u9fffA-Za-z0-9，。、：；（）()%￥¥.,:;!?\-/]", line))
        if readable / max(len(line), 1) < 0.5:
            continue
        lines.append(line)
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    if len(out) > MAX_TEXT_CHARS:
        out = out[:MAX_TEXT_CHARS].rstrip() + "\n…(截断)"
    return out


def _page_summary(html: str) -> str | None:
    t = _plain(html)
    if len(t) < 40:
        return None
    return t[:SUMMARY_CHARS]


def _tenderfile_summary(text: str) -> str | None:
    t = clean_extracted_text(text)
    if not t:
        return None
    return t[:SUMMARY_CHARS]


def _download_and_extract(http: HttpSession, source_id: str, detail_url: str,
                          attachments: list[tuple[str, str]], cookie: str = "") -> tuple[dict | None, str]:
    """附件候选列表 → 下载 + 魔数校验 + 正文提取。成功返回 (tenderFile, "")，失败返回 (None, error)。"""
    last_err = ""
    for url, fmt in attachments[:3]:  # 最多试 3 个附件
        digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:16]
        dest = TENDERFILE_DIR / source_id / f"{digest}.{fmt}"
        ok, err = download_attachment(http, url, dest, referer=detail_url, cookie=cookie)
        if not ok:
            last_err = err
            continue
        # 魔数校验 + 嗅探判型：扩展名与真实格式不符时改判（防把登录页/HTML 当附件、防 .doc 伪装 .pdf）
        actual = _sniff_format(dest.read_bytes()[:2048])
        if actual is None:
            dest.unlink(missing_ok=True)
            last_err = "download_failed: unrecognized content (likely a login/notice page)"
            continue
        if actual != fmt:
            dest2 = dest.with_suffix("." + actual)
            dest.replace(dest2)
            dest = dest2
            fmt = actual
        try:
            text = clean_extracted_text(extract_text(dest, fmt))
        except Exception as e:  # noqa: BLE001 —— 解析失败如实失败并清理
            dest.unlink(missing_ok=True)
            last_err = f"extract_failed: {str(e)[:200]}"
            continue
        if not text:
            dest.unlink(missing_ok=True)
            last_err = "extract_failed: empty text"
            continue
        return {
            "path": str(dest.relative_to(ROOT)).replace("\\", "/"),
            "text": text,
            "sourceUrl": url,
            "format": "docx" if fmt == "doc" else fmt,  # 契约 enum：旧版 .doc 归一为 Word 族 docx
        }, ""
    return None, last_err or "attachment_fetch_failed"


def ggzy_detail_page_url(detail_url: str) -> str | None:
    """ggzy a 页 URL → 正文 b 页 URL（同 id，/html/a/ → /html/b/）。非 ggzy 形态返回 None。"""
    if "www.ggzy.gov.cn" not in detail_url:
        return None
    if "/html/b/" in detail_url:
        return detail_url
    m = re.match(r"(https?://[^/]+/information/[^/]+/html/)a(/.*\.html)$", detail_url)
    if not m:
        return None
    return m.group(1) + "b" + m.group(2)


def _extract_ggzy_origin_and_fields(html: str) -> dict:
    """ggzy/jsggzy 详情页静态结构的原发与字段（P5 实测结论）：

    - 信息来源：<label id="platformName">上海</label> → 原发平台名（结构化）
    - 「原文链接地址」锚点 href 为空且 display:none（JS 动态填充）→ 静态拿不到，靠正文文本里的来源 URL 兜底
    - 内容区结构化字段：项目ID/项目编号/交易机构/交易底价/成交价格 → 项目编号+金额回填
    返回 {"source": str|None, "url": str|None, "fields": {project_code/amount/amount_text}}
    """
    out: dict = {"source": None, "url": None, "fields": {}}
    m = re.search(r'信息来源[：:]\s*<label[^>]*id="platformName"[^>]*>([^<]*)</label>', html)
    if m and m.group(1).strip():
        out["source"] = m.group(1).strip()
    full = _plain(html)
    # 文本来源行兜底（jsggzy 静态页带「来源：XX交易中心 + URL」）
    out["url"] = origin_url(full)
    for line in origin_lines(full):
        ent = re.sub(r"^原文链接.*$", "", line).strip(" :：,，。.、")
        if ent and not out["source"] and len(ent) >= 2:
            out["source"] = ent[:120]
            break
    m = re.search(r"项目编号[：:]\s*([^;\s]+)", full)
    if m:
        out["fields"]["project_code"] = m.group(1).strip()
    m = re.search(r"(?:成交价格|成交金额|交易底价)[：:]\s*([\d,\.]+\s*(?:万元|元|万)?)", full)
    if m:
        at = m.group(1).strip()
        out["fields"]["amount_text"] = at
        nm = re.match(r"([\d,\.]+)\s*(万元|元|万)?$", at)
        if nm:
            try:
                num = float(nm.group(1).replace(",", ""))
            except ValueError:
                num = None
            if num is not None:
                out["fields"]["amount"] = num * 10000 if nm.group(2) in ("万元", "万") else num
    # 交易机构/招标人/采购人 → buyer（采购人，原发 b 页静态结构里就有）
    m = re.search(r"(?:交易机构|招标人|采购人|采购单位)[：:]\s*([^;|<]{2,60})", full)
    if m:
        buyer = re.sub(r"\s+", " ", m.group(1)).strip()
        if buyer and "原文链接" not in buyer:
            out["fields"]["buyer"] = buyer[:120]
    # 中标/成交供应商 → winner（结果公告的 b 页）
    m = re.search(r"(?:中标供应商|成交供应商|中标人|中标单位)[：:]\s*([^\n|;；，,。、]{2,80})", full)
    if m:
        w = re.sub(r"[（(][^）)]*[）)]", " ", m.group(1)).strip()
        w = re.sub(r"\s+", " ", w).strip()
        if w and len(w) >= 4 and "原文链接" not in w:
            out["fields"]["winner"] = w[:80]
    return out


def _fetch_ggzy_http(detail_url: str, http: HttpSession, source_id: str = "ggzy") -> dict:
    """ggzy/jsggzy：正文 b 页 SSR 直取（实测全文可达）；b 页内附件链接常规发现。

    P5：附带原发线索（origin）与结构化字段（fields：项目编号/金额），供回填链路使用。
    """
    out: dict = {"ok": False, "error": None, "summary": None, "tenderFile": None, "origin": None, "fields": None}
    page_url = ggzy_detail_page_url(detail_url) or detail_url
    try:
        html = http.get_text(page_url, headers={"Referer": "https://www.ggzy.gov.cn/"})
    except Exception as e:  # noqa: BLE001
        out["error"] = f"ggzy_page_failed: {str(e)[:200]}"
        return out
    if not html or len(html) < 200:
        out["error"] = "ggzy_page_empty_or_blocked"
        return out
    origin_info = _extract_ggzy_origin_and_fields(html)
    if origin_info.get("source") or origin_info.get("url"):
        out["origin"] = {"source": origin_info["source"], "url": origin_info["url"]}
    if origin_info.get("fields"):
        out["fields"] = origin_info["fields"]
    page_summary = _page_summary(html)
    # b 页全文（含结构化字段）比 200 字摘要信息量大得多：无附件时用全文做摘要（封顶 2000）
    full_text = _plain(html)
    summary_fallback = full_text[:2000] if len(full_text) > 200 else page_summary
    attachments = discover_attachment_urls(html, page_url)
    if attachments:
        tf, err = _download_and_extract(http, source_id, page_url, attachments)
        if tf:
            out["ok"] = True
            out["summary"] = _tenderfile_summary(tf["text"])
            out["tenderFile"] = tf
            return out
        out["summary"] = summary_fallback
        out["error"] = err
        return out
    out["summary"] = summary_fallback
    out["error"] = "no_attachment_link"
    return out


# ---------------------------------------------------------------- WebBridge 详情 ---

BRIDGE_EXTRACT_JS = r"""(() => {
  const text = (document.body && document.body.innerText || '').replace(/\s+/g, ' ');
  const dl = [];
  document.querySelectorAll('a,button,input,span,div').forEach(e => {
    const h = e.getAttribute('href') || '';
    const on = e.getAttribute('onclick') || '';
    const t = (e.textContent || e.value || '').trim().slice(0, 40);
    if (/下载|附件|招标文件|采购文件|\.pdf|\.docx?|\.wps|file|down/i.test(t + h + on)) {
      dl.push({t, h: h.slice(0, 300), on: on.slice(0, 300)});
    }
  });
  return JSON.stringify({title: document.title, len: text.length, text: text.slice(0, 12000), links: dl.slice(0, 12)});
})()"""

# 江苏会员门信号（正文/附件被登录挡住时的页面文本特征）
JIANGSU_GATE_TEXT = ("正式会员", "请登录")

# 登录态信号：登录成功后页面出现「退出」且不再出现「请登录」
JS_LOGIN_STATE = r"""(() => {
  const text = (document.body && document.body.innerText || '').replace(/\s+/g, ' ');
  return JSON.stringify({href: location.href, has_quit: /退出/.test(text), has_login_btn: /请登录|立即登录/.test(text), head: text.slice(0, 200)});
})()"""

JS_FILL_LOGIN = r"""(() => {
  const tab = [...document.querySelectorAll('li,div,a,span')].find(e =>
    /会员登录/.test(e.textContent || '') && ((e.textContent || '').trim().length <= 8));
  if (tab) tab.click();
  const u = document.querySelector("input[name=loginUserId], #loginUserId");
  const p = document.querySelector("input[name=loginPassword], #loginPassword");
  if (!u || !p) return JSON.stringify({ok: false, error: "no_inputs"});
  u.value = __USER__;
  p.value = __PASS__;
  u.dispatchEvent(new Event('input', {bubbles: true}));
  p.dispatchEvent(new Event('input', {bubbles: true}));
  const btn = document.querySelector("input.login_button") ||
    [...document.querySelectorAll('input[type=submit],button')].find(b => /^登录$/.test((b.value||b.textContent||'').trim()));
  if (!btn) return JSON.stringify({ok: false, error: "no_button"});
  btn.click();
  return JSON.stringify({ok: true});
})()"""

JS_CAPTCHA_STATE = r"""(() => {
  const box = document.querySelector('#captcha-box');
  const text = (document.body && document.body.innerText || '').replace(/\s+/g, ' ');
  return JSON.stringify({captcha_box: !!box, captcha_rendered: box ? box.innerHTML.length > 50 : false,
    has_quit: /退出/.test(text), still_login: /请登录|登录成功/.test(text), href: location.href});
})()"""

# 浏览器内同步 XHR 下载（携带全部 Cookie 含 HttpOnly），返回 base64；
# 标准模式走 arraybuffer；quirks 模式（同步 XHR 禁 responseType）退 overrideMimeType 字节通道
JS_XHR_DOWNLOAD = r"""(() => {
  const toB64 = (bytes) => {
    let binary = '';
    const CH = 32768;
    for (let i = 0; i < bytes.length; i += CH) {
      binary += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
    }
    return btoa(binary);
  };
  const sendSync = (url, ref, useRespType) => {
    const x = new XMLHttpRequest();
    if (useRespType) { try { x.responseType = 'arraybuffer'; } catch (e) {} }
    x.open('GET', url, false);
    try { x.setRequestHeader('Referer', ref); } catch (e) {}
    x.send();
    return x;
  };
  let bytes = null;
  try {
    // 标准模式：arraybuffer
    const x1 = sendSync(__URL__, __REF__, true);
    if (x1.status !== 200) return JSON.stringify({ok: false, status: x1.status});
    if (x1.response instanceof ArrayBuffer) bytes = new Uint8Array(x1.response);
  } catch (e) {
    // quirks 文档：同步 XHR 禁 responseType → 字节通道
    try {
      const x2 = new XMLHttpRequest();
      x2.open('GET', __URL__, false);
      try { x2.overrideMimeType('text/plain; charset=x-user-defined'); } catch (e2) {}
      try { x2.setRequestHeader('Referer', __REF__); } catch (e3) {}
      x2.send();
      if (x2.status !== 200) return JSON.stringify({ok: false, status: x2.status});
      const s = x2.responseText || '';
      bytes = new Uint8Array(s.length);
      for (let i = 0; i < s.length; i++) bytes[i] = s.charCodeAt(i) & 0xff;
    } catch (e4) {
      return JSON.stringify({ok: false, error: String(e4).slice(0, 150)});
    }
  }
  if (!bytes || !bytes.length) return JSON.stringify({ok: false, error: 'no_body'});
  return JSON.stringify({ok: true, len: bytes.length, b64: toB64(bytes)});
})()"""

# 浏览器内下载大小上限（base64 经 WS 回传，太大不划算；超限如实失败）
MAX_BRIDGE_DOWNLOAD_BYTES = 15 * 1024 * 1024


def _bridge_eval_json(session: str, js: str) -> dict:
    from crawl import webbridge_client as wb

    r = wb.evaluate(js, session=session)
    val = (r.get("data") or {}).get("value")
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {"raw": val[:300]}
    return val if isinstance(val, dict) else {}


def _err_text(e) -> str:
    """把任意错误结构安全转成短字符串（桥/扩展 error 可能是 dict {code,message}）。"""
    if e is None:
        return ""
    if isinstance(e, str):
        return e
    if isinstance(e, dict):
        return str(e.get("message") or e.get("code") or e)
    return str(e)


# 本轮详情抓取开过的 bridge 会话（用完统一关闭，防浏览器堆积标签页吃内存）
_OPEN_BRIDGE_SESSIONS: set[str] = set()


def close_bridge_tabs() -> int:
    """关闭本轮详情抓取开过的所有 bridge tab，返回关闭数。"""
    from crawl import webbridge_client as wb

    closed = 0
    for session in list(_OPEN_BRIDGE_SESSIONS):
        try:
            for t in wb.list_tabs(session=session):
                if wb.close_tab(t.get("tabId"), session=session):
                    closed += 1
        except Exception:
            pass
    _OPEN_BRIDGE_SESSIONS.clear()
    return closed


def _bridge_page(source_id: str, detail_url: str, *, wait_sec: float = 10.0) -> dict:
    """WebBridge 真浏览器打开详情页，返回 {text, links, cookie, session} 或 {error}。"""
    from crawl import webbridge_client as wb

    st = wb.ensure_bridge(wait_sec=60)
    if not st.get("bridge") or not st.get("extensions"):
        return {"error": "bridge_unavailable"}
    session = f"tf-{source_id}-{hashlib.md5(detail_url.encode()).hexdigest()[:8]}"
    nav = wb.navigate(detail_url, session=session, group_title="tenderfile", new_tab=True)
    if not nav.get("ok"):
        return {"error": f"bridge_navigate_failed: {_err_text(nav.get('error'))[:120]}"}
    _OPEN_BRIDGE_SESSIONS.add(session)
    time.sleep(wait_sec + random.uniform(0, 3))
    page = _bridge_eval_json(session, BRIDGE_EXTRACT_JS)
    cookie = ""
    try:
        c = wb.export_document_cookie(session)
        if c.get("ok"):
            cookie = c.get("cookie") or ""
    except Exception:  # noqa: BLE001
        pass
    text = page.get("text") or ""
    if len(text) < 100:
        return {"error": "bridge_page_empty", "text": text, "links": [], "cookie": cookie, "session": session}
    return {"text": text, "links": list(page.get("links") or []), "cookie": cookie, "session": session}


# 桥内取验证码（IIFE 返回 Promise；桥 evaluate 会 await Promise 表达式，但不执行 async 函数定义）
JS_BRIDGE_CAPTCHA = r"""(() => fetch('/common/img.jsp?n=l&' + Math.random(), {credentials: 'include'})
  .then(r => { if (!r.ok) return JSON.stringify({ok: false, status: r.status}); return r.arrayBuffer(); })
  .then(buf => {
    const bytes = new Uint8Array(buf);
    let bin = '';
    const CH = 32768;
    for (let i = 0; i < bytes.length; i += CH) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
    return JSON.stringify({ok: true, b64: btoa(bin)});
  })
  .catch(e => JSON.stringify({ok: false, error: String(e).slice(0, 120)})))()"""

# 桥内提交账号登录：IIFE 立即执行（桥 evaluate 不执行函数定义，只执行表达式）：
# 切 #zh（账号登录 tab，loginType=userId）→ 填三字段 → 点可见登录按钮；实参占位 __U__/__P__/__Y__
JS_BRIDGE_SUBMIT = r"""((u, p, y) => {
  const zh = document.querySelector('#zh');
  if (zh) { zh.click(); }
  const user = document.querySelector("input[name=loginUserId], #loginUserId");
  const pwd = document.querySelector("input[name=loginPassword], #loginPassword");
  const yzm = document.querySelector("input[name=yzm], #yzm");
  if (!user || !pwd || !yzm) return JSON.stringify({ok: false, error: 'no_inputs'});
  user.value = u; pwd.value = p; yzm.value = y;
  user.dispatchEvent(new Event('input', {bubbles: true}));
  pwd.dispatchEvent(new Event('input', {bubbles: true}));
  yzm.dispatchEvent(new Event('input', {bubbles: true}));
  const btn = [...document.querySelectorAll('input.login_button')].find(b => b.offsetParent !== null);
  if (btn) { btn.click(); return JSON.stringify({ok: true}); }
  return JSON.stringify({ok: false, error: 'no_visible_button'});
})(__U__, __P__, __Y__)"""

JS_LOGIN_PAGE_STATE = r"""(() => {
  const text = (document.body && document.body.innerText || '').replace(/\s+/g, ' ');
  return JSON.stringify({
    href: location.href,
    has_quit: /退出/.test(text),
    captcha_wrong: /验证码.{0,10}(错误|不正确|失效|有误)/.test(text),
    pass_wrong: /密码.{0,10}(错误|不正确)/.test(text),
    has_phone_mask: /1[3-9]\d\*{4}\d{4}/.test(text),
  });
})()"""


def _jiangsu_bridge_login_ocr(user: str, pwd: str) -> str:
    """桥内账号登录：页面取数字验证码 → AI OCR → 提交；验证码错误换图重试（限 3）。

    返回 ok / captcha_wrong_loop / no_inputs / bridge_unavailable / bad_credentials。
    无需人工；滑块只在异常兜底时出现（见 ensure_jiangsu_login）。
    """
    import base64

    from crawl import captcha_ocr
    from crawl import webbridge_client as wb

    st = wb.ensure_bridge(wait_sec=60)
    if not st.get("bridge") or not st.get("extensions"):
        return "bridge_unavailable"
    session = "js-login-ocr"
    wb.navigate("https://user.zhaobiao.cn/login.html", session=session, group_title="江苏登录", new_tab=True)
    time.sleep(6)
    for _ in range(3):
        # 已登录？
        state = _bridge_eval_json(session, JS_LOGIN_PAGE_STATE)
        if state.get("has_quit") or state.get("has_phone_mask"):
            return "ok"
        # 取验证码（页内 fetch，会话绑定）
        r = wb.evaluate(JS_BRIDGE_CAPTCHA, session=session)
        val = (r.get("data") or {}).get("value")
        b64 = None
        if isinstance(val, str):
            try:
                obj = json.loads(val)
                b64 = obj.get("b64")
            except Exception:
                pass
        if not b64:
            return "no_inputs"
        img_bytes = base64.b64decode(b64)
        yzm = captcha_ocr.ocr_captcha(img_bytes)
        if not yzm:
            continue
        r2 = wb.evaluate(
            JS_BRIDGE_SUBMIT.replace("__U__", json.dumps(user)).replace("__P__", json.dumps(pwd)).replace("__Y__", json.dumps(yzm)),
            session=session,
        )
        sub = (r2.get("data") or {}).get("value")
        if isinstance(sub, str):
            try:
                sub = json.loads(sub)
            except Exception:
                pass
        if not (sub or {}).get("ok"):
            return "no_inputs"
        time.sleep(5)
        state2 = _bridge_eval_json(session, JS_LOGIN_PAGE_STATE)
        if state2.get("has_quit") or state2.get("has_phone_mask"):
            return "ok"
        if state2.get("pass_wrong"):
            return "bad_credentials"
        if state2.get("captcha_wrong"):
            time.sleep(1.5)
            continue
        return "login_failed"
    return "captcha_wrong_loop"


def ensure_jiangsu_login() -> str:
    """确保江苏会员已登录（账号来自 .env JIANGSU_ZHAOBIAO_USER/PASS）。

    顺序：① 若 config/ocr_api.json 已启用 → HTTP 验证码登录（AI OCR，无需浏览器）
         ② WebBridge 桥内登录（AI OCR 自动；异常弹滑块时人工拖一次，登记待办）
    返回：ok / need_human_captcha / need_ocr_fix / no_creds / bridge_unavailable / login_failed。
    """
    from crawl import captcha_ocr

    if captcha_ocr.load_ocr_cfg().get("enabled"):
        state = _jiangsu_login_http()
        if state == "ok":
            return "ok"

    from crawl import webbridge_client as wb
    from crawl.captcha_queue import open_todo

    sys.path.insert(0, str(ROOT / "scripts"))
    from db import load_env

    env = load_env()
    user = (env.get("JIANGSU_ZHAOBIAO_USER") or "").strip()
    pwd = (env.get("JIANGSU_ZHAOBIAO_PASS") or "").strip()
    if not user or not pwd:
        return "no_creds"
    # ② 桥内 AI OCR 登录（无人工）
    state2 = _jiangsu_bridge_login_ocr(user, pwd)
    if state2 == "ok":
        return "ok"
    if state2 in ("bad_credentials", "no_inputs", "bridge_unavailable"):
        return state2 if state2 == "bridge_unavailable" else f"login_failed: {state2}"
    # OCR 连续失败/异常 → 滑块人工兜底（fill+click，弹滑块时登记待办）
    st = wb.ensure_bridge(wait_sec=60)
    if not st.get("bridge") or not st.get("extensions"):
        return "bridge_unavailable"
    session = "js-login"
    wb.navigate("https://user.zhaobiao.cn/login.html", session=session, group_title="江苏登录", new_tab=True)
    time.sleep(6)
    wb.evaluate(JS_FILL_LOGIN.replace("__USER__", json.dumps(user)).replace("__PASS__", json.dumps(pwd)),
                session=session)
    time.sleep(6)
    state3 = _bridge_eval_json(session, JS_CAPTCHA_STATE)
    if state3.get("has_quit"):
        return "ok"
    if state3.get("captcha_box") or (not state3.get("has_quit") and state3.get("still_login")):
        open_todo(
            "jiangsu_zhaobiao",
            "https://user.zhaobiao.cn/login.html",
            title="江苏招标网登录滑块（人工拖一次，会话长期复用）",
            note="账号已自动填入；请在 Chrome「江苏登录」标签页人工完成滑块验证。完成后无需任何操作，采集员自动复用登录会话。",
        )
        return "need_human_captcha"
    return "login_failed"


JIANGSU_LOGIN_POST = "https://user.zhaobiao.cn/ssologin.do?method=loginPost"
JIANGSU_LOGIN_PAGE = "https://user.zhaobiao.cn/login.html"
JIANGSU_CAPTCHA_URL = "https://user.zhaobiao.cn/common/img.jsp?n=l&{rand}"
_JIANGSU_LOGIN_MAX_TRIES = 3


def _jiangsu_login_http() -> str:
    """HTTP 账号密码登录：数字验证码 OCR 自动识别（AI API 优先，确定性兜底）。

    成功 → 登录 Cookie 落 cookie_store（HTTP 详情/附件路径直接复用）；
    验证码错误 → 换图重试（限次）；密码/账号错误 → login_failed 如实返回。
    """
    from crawl import captcha_ocr
    from crawl import cookie_store
    from crawl.captcha_queue import open_todo

    sys.path.insert(0, str(ROOT / "scripts"))
    from db import load_env

    env = load_env()
    user = (env.get("JIANGSU_ZHAOBIAO_USER") or "").strip()
    pwd = (env.get("JIANGSU_ZHAOBIAO_PASS") or "").strip()
    if not user or not pwd:
        return "no_creds"

    http = HttpSession("jiangsu_zhaobiao")
    last_reason = ""
    for attempt in range(_JIANGSU_LOGIN_MAX_TRIES):
        try:
            _, raw, _ = http.request(JIANGSU_LOGIN_PAGE, headers={"Referer": "https://jiangsu.zhaobiao.cn/"})
            html = raw.decode("gbk", "ignore")
        except Exception as e:  # noqa: BLE001
            return f"login_failed: page {str(e)[:120]}"
        # 隐藏字段
        payload = {}
        for m in re.finditer(r"<input[^>]+>", html, re.I):
            tag = m.group(0)
            nm = re.search(r'name=["\']([^"\']+)["\']', tag, re.I)
            val = re.search(r'value=["\']([^"\']*)["\']', tag, re.I)
            typ = (re.search(r'type=["\']([^"\']+)["\']', tag, re.I) or [None, "text"])[1].lower()
            if not nm or typ in {"submit", "button", "image"}:
                continue
            payload[nm.group(1)] = val.group(1) if val else ""
        # 数字验证码图片（会话绑定，带 Cookie）
        cookie_hdr = "; ".join(f"{c.name}={c.value}" for c in http.cj)
        img_bytes = None
        try:
            import random as _r

            _, img_bytes, _ = http.request(
                JIANGSU_CAPTCHA_URL.format(rand=str(_r.random())),
                headers={"Referer": JIANGSU_LOGIN_PAGE, "Cookie": cookie_hdr},
            )
        except Exception:  # noqa: BLE001
            pass
        if not img_bytes or len(img_bytes) < 500:
            last_reason = "captcha_image_failed"
            continue
        yzm = captcha_ocr.ocr_captcha(img_bytes)
        if not yzm:
            last_reason = "captcha_ocr_failed"
            continue
        payload["loginType"] = "userId"  # 账号密码登录（login_2.js：会员登录 tab 设 loginType=userId，手机=mobile）
        payload["loginUserId"] = user
        payload["loginPassword"] = pwd
        # 同一张验证码的大小写变体重试（服务端大小写口径不明，先试原读、再小写、大写、换形）
        variants = []
        for v in (yzm, yzm.lower(), yzm.upper(), yzm.swapcase()):
            if v not in variants:
                variants.append(v)
        tried_ok = False
        for yv in variants:
            payload["yzm"] = yv
            try:
                code, raw2, final2 = http.request(
                    JIANGSU_LOGIN_POST,
                    data=urlencode(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Referer": JIANGSU_LOGIN_PAGE,
                        "Origin": "https://user.zhaobiao.cn",
                        "Cookie": cookie_hdr,
                    },
                )
            except Exception as e:  # noqa: BLE001
                last_reason = f"login_post_failed: {str(e)[:120]}"
                break
            text2 = raw2.decode("gbk", "ignore")
            if re.search(r"验证码.{0,10}(错误|不正确|失效|有误)", text2):
                last_reason = f"captcha_wrong(yzm={yv})"
                time.sleep(1.0)
                continue
            if re.search(r"密码.{0,10}(错误|不正确)|用户.{0,8}(不存在|未注册)", text2):
                return "login_failed: bad_credentials"
            tried_ok = True
            break
        if not tried_ok:
            continue
        # SSO 回跳：成功响应带 JS 跳转 loginSuccess（种 .zhaobiao.cn 跨域会话 Cookie），必须跟随
        m_ss = re.search(r"(?:location\.(?:href|replace)\s*=\s*[\"'])([^\"']+)[\"']", text2)
        sso_path = m_ss.group(1) if m_ss else "/ssologin.do?method=loginSuccess&loginWeb=www"
        if sso_path.startswith("/"):
            sso_url = "https://user.zhaobiao.cn" + sso_path
        elif sso_path.startswith(("http://", "https://")):
            sso_url = sso_path
        else:
            sso_url = None
        if sso_url:
            try:
                http.request(sso_url, headers={"Referer": JIANGSU_LOGIN_PAGE,
                                               "Cookie": "; ".join(f"{c.name}={c.value}" for c in http.cj)})
            except Exception:  # noqa: BLE001 —— SSO 回跳失败不判死，用会员中心验证兜底
                pass
        # 真实验证登录态：带 Cookie 访问会员中心，成功页含账户信息、失败会回登录页
        jar = "; ".join(f"{c.name}={c.value}" for c in http.cj)
        if not jar:
            last_reason = "login_failed: no_session_cookie"
            continue
        try:
            _, raw3, _ = http.request(
                "https://user.zhaobiao.cn/homePageUc.do",
                headers={"Referer": JIANGSU_LOGIN_PAGE, "Cookie": jar},
            )
            text3 = raw3.decode("gbk", "ignore")
        except Exception as e:  # noqa: BLE001
            last_reason = f"login_verify_failed: {str(e)[:120]}"
            continue
        if ("账户管理" in text3 or "会员中心" in text3) and "loginUserId" not in text3[:2000]:
            cookie_store.save_cookie_header(
                "jiangsu_zhaobiao", jar, meta={"from": "login_captcha_http", "user": user}
            )
            return "ok"
        last_reason = "login_failed: verify_not_logged_in"
        time.sleep(2)
    if last_reason.startswith("captcha_wrong") or last_reason in ("captcha_image_failed", "captcha_ocr_failed"):
        open_todo(
            "jiangsu_zhaobiao",
            JIANGSU_LOGIN_PAGE,
            title="江苏招标网登录数字验证码（OCR 未通过）",
            note=f"自动识别连续失败：{last_reason}。已配置 config/ocr_api.json 可用 AI 识别；或人工登录后保存 Cookie。",
        )
        return f"need_ocr_fix: {last_reason}"
    return last_reason or "login_failed"


def _bridge_download_b64(session: str, url: str, referer: str) -> tuple[bytes | None, str]:
    """浏览器内同步 XHR 下载（含 HttpOnly Cookie），返回 (bytes, error)。"""
    from crawl import webbridge_client as wb

    js = JS_XHR_DOWNLOAD.replace("__URL__", json.dumps(url)).replace("__REF__", json.dumps(referer))
    r = _bridge_eval_json(session, js)
    if not r.get("ok"):
        return None, f"bridge_download_failed: status={r.get('status')} err={r.get('error') or 'unknown'}"
    b64 = r.get("b64") or ""
    try:
        import base64

        data = base64.b64decode(b64)
    except Exception as e:  # noqa: BLE001
        return None, f"bridge_download_decode_failed: {str(e)[:120]}"
    if len(data) > MAX_BRIDGE_DOWNLOAD_BYTES:
        return None, f"bridge_download_oversized: {len(data)} bytes > {MAX_BRIDGE_DOWNLOAD_BYTES}"
    return data, ""


def _bridge_summary(text: str) -> str | None:
    """从桥抓取的页面全文定位正文摘要：优先「正文内容/公告正文/·公告摘要：」后的片段，退化取全文头部。"""
    t = clean_extracted_text(text)
    if len(t) < 40:
        return None
    for marker in ("正文内容", "公告正文", "·公告摘要：", "部分信息内容如下", "正文摘要"):
        idx = t.find(marker)
        if idx != -1:
            seg = t[idx + len(marker):].strip()
            if len(seg) >= 40:
                return seg[:SUMMARY_CHARS]
            break
    return t[:SUMMARY_CHARS]


def _bridge_attachment_candidates(links: list, page_url: str) -> list[tuple[str, str]]:
    """桥抓取的下载控件 → 附件候选 URL（href 直链 / onclick 内嵌 URL）。"""
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for it in links or []:
        if not isinstance(it, dict):
            continue
        h = str(it.get("h") or "").strip()
        on = str(it.get("on") or "").strip()
        urls: list[str] = []
        if h.startswith(("http://", "https://")):
            urls.append(h)
        urls += re.findall(r"['\"](https?://[^'\"]+)['\"]", on)
        urls += [urljoin(page_url, u) for u in re.findall(r"['\"](/[^'\"]*(?:file|down|attach|\.pdf|\.doc)[^'\"]*)['\"]", on, re.I)]
        for u in urls:
            if u in seen:
                continue
            path = urlparse(u).path.lower()
            fmt = None
            for ext, f in _EXT_FORMAT.items():
                if path.endswith("." + ext):
                    fmt = f
                    break
            if fmt is None and re.search(r"file|down|attach", path, re.I):
                fmt = "pdf"  # 未知形态按 pdf 尝试，魔数校验兜底
            if fmt:
                seen.add(u)
                found.append((u, fmt))
    return found


def fetch_detail_via_bridge(source_id: str, detail_url: str) -> dict:
    """WebBridge 详情：正文可达（摘要填充）；江苏账号登录后附件可下载，登录门未过时如实 null。"""
    out: dict = {"ok": False, "error": None, "summary": None, "tenderFile": None}
    if not detail_url or not detail_url.startswith(("http://", "https://")):
        out["error"] = "no_detail_url"
        return out
    page = _bridge_page(source_id, detail_url)
    if "error" in page and not page.get("text"):
        out["error"] = page["error"]
        return out

    text = page.get("text") or ""
    out["summary"] = _bridge_summary(text)

    if source_id == "jiangsu_zhaobiao" and any(g in text for g in JIANGSU_GATE_TEXT):
        # 江苏有账号：① 桥内 AI OCR 自动登录（修桥会话）② HTTP 验证码登录（补 Cookie 库）③ 滑块人工兜底
        sys.path.insert(0, str(ROOT / "scripts"))
        from db import load_env

        env = load_env()
        user = (env.get("JIANGSU_ZHAOBIAO_USER") or "").strip()
        pwd = (env.get("JIANGSU_ZHAOBIAO_PASS") or "").strip()
        if user and pwd:
            if _jiangsu_bridge_login_ocr(user, pwd) == "ok":
                page = _bridge_page(source_id, detail_url)
                text = page.get("text") or ""
                out["summary"] = _bridge_summary(text) or out["summary"]
            else:
                state = ensure_jiangsu_login()
                if state == "ok":
                    page = _bridge_page(source_id, detail_url)
                    text = page.get("text") or ""
                    out["summary"] = _bridge_summary(text) or out["summary"]
                else:
                    out["error"] = f"detail_login_{state}"
                    return out
    if source_id == "chinabidding" and "立即注册" in text:
        out["error"] = "detail_login_wall"  # 附件需注册登录；正文（略）摘要仍如实给出
        return out

    # 附件下载：HTTP+页面 Cookie 优先（稳定、无 CORS 限制，实测 bidFiledown.jsp 可下）；
    # 失败退浏览器内同步 XHR（含 HttpOnly Cookie）；再失败如实报最后一步原因
    attachments = _bridge_attachment_candidates(page.get("links") or [], detail_url)
    if not attachments:
        out["error"] = "no_attachment_link"
        return out

    last_err = ""
    http = HttpSession(source_id)
    tf, err = _download_and_extract(http, source_id, detail_url, attachments,
                                    cookie=page.get("cookie") or "")
    if tf:
        out["ok"] = True
        out["error"] = None
        out["summary"] = _tenderfile_summary(tf["text"])
        out["tenderFile"] = tf
        return out
    if err:
        last_err = err

    # 浏览器内下载兜底（含 HttpOnly cookie）
    session = page.get("session") or ""
    for url, fmt in attachments[:3]:
        raw, err2 = _bridge_download_b64(session, url, detail_url) if session else (None, "no_session")
        if raw is None:
            last_err = err2 or last_err
            continue
        actual = _sniff_format(raw)
        if actual is None:
            last_err = "download_failed: unrecognized content (likely a login/notice page)"
            continue
        fmt = actual
        digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:16]
        dest = TENDERFILE_DIR / source_id / f"{digest}.{fmt}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        try:
            text = clean_extracted_text(extract_text(dest, fmt))
        except Exception as e:  # noqa: BLE001
            dest.unlink(missing_ok=True)
            last_err = f"extract_failed: {str(e)[:200]}"
            continue
        if not text:
            dest.unlink(missing_ok=True)
            last_err = "extract_failed: empty text"
            continue
        out["ok"] = True
        out["error"] = None
        out["summary"] = _tenderfile_summary(text)
        out["tenderFile"] = {
            "path": str(dest.relative_to(ROOT)).replace("\\", "/"),
            "text": text,
            "sourceUrl": url,
            "format": "docx" if fmt == "doc" else fmt,  # 契约 enum：旧版 .doc 归一为 Word 族 docx
        }
        return out

    out["error"] = last_err or "attachment_fetch_failed"
    return out


def fetch_tenderfile(source_id: str, detail_url: str, *, http: HttpSession | None = None) -> dict:
    """详情页 → 附件发现 → 下载 → 正文清洗（按 DETAIL_MODES 路由）。

    返回 {"ok": bool, "error": str|None, "summary": str|None,
          "tenderFile": {"path","text","sourceUrl","format"} | None}
    任何一步失败如实记录 error，tenderFile=None，绝不编造。
    """
    out: dict = {"ok": False, "error": None, "summary": None, "tenderFile": None}
    if not detail_url or not detail_url.startswith(("http://", "https://")):
        out["error"] = "no_detail_url"
        return out
    mode = DETAIL_MODES.get(source_id)
    if mode is None:
        out["error"] = f"unknown_platform:{source_id}"
        return out
    if mode == "ggzy_http":
        return _fetch_ggzy_http(detail_url, http or HttpSession(source_id), source_id=source_id)
    if mode == "bridge":
        return fetch_detail_via_bridge(source_id, detail_url)
    if mode == "bridge_vaptcha":
        return fetch_cebpub_via_bridge(detail_url)
    if mode == "blocked_regwall":
        out["error"] = "detail_register_wall"  # 注册墙（手机号+短信验证码），三级不可直取，待账号
        return out

    # mode == "http"（ccgp / yfbzb 等）
    http = http or HttpSession(source_id)
    try:
        html = http.get_text(detail_url, headers={"Referer": detail_url})
    except Exception as e:  # noqa: BLE001
        out["error"] = f"detail_page_failed: {str(e)[:200]}"
        return out
    if not html or len(html) < 200:
        out["error"] = "detail_page_empty_or_blocked"
        return out

    page_summary = _page_summary(html)
    attachments = discover_attachment_urls(html, detail_url)
    if not attachments:
        out["summary"] = page_summary
        out["error"] = "no_attachment_link"
        return out
    tf, err = _download_and_extract(http, source_id, detail_url, attachments)
    if tf:
        out["ok"] = True
        out["error"] = None
        out["summary"] = _tenderfile_summary(tf["text"])
        out["tenderFile"] = tf
        return out
    out["summary"] = page_summary
    out["error"] = err
    return out


# ---------------------------------------------------------------- cebpub（vaptcha 门 + DES 接口解密） ---

CEBPUB_DES_KEY = b"1qaz@wsx"  # SPA app.js 内嵌：DES-ECB-PKCS7，key="1qaz@wsx3e" 取前 8 字节


def cebpub_des_decrypt(b64: str) -> str:
    """cebpub API 响应解密（DES-ECB-PKCS7，密钥来自其前端 app.js）。"""
    import base64

    try:
        from Crypto.Cipher import DES
    except ImportError as e:  # noqa: BLE001
        raise RuntimeError("pycryptodome not installed (cebpub api decrypt unavailable)") from e
    raw = base64.b64decode(b64)
    data = DES.new(CEBPUB_DES_KEY, DES.MODE_ECB).decrypt(raw)
    pad = data[-1]
    if 1 <= pad <= 8:
        data = data[:-pad]
    return data.decode("utf-8", "replace")


def fetch_cebpub_via_bridge(detail_url: str) -> dict:
    """cebpub 详情：SPA vaptcha 人工验证后内容才渲染；桥内已验证时抓附件（页面 Cookie→HTTP 或桥内下载）。

    vaptcha 未过时如实 detail_vaptcha_gated 并登记待办（验证码不可绕过，人工一次后会话复用）。
    """
    from crawl.captcha_queue import open_todo

    out: dict = {"ok": False, "error": None, "summary": None, "tenderFile": None}
    page = _bridge_page("cebpub", detail_url, wait_sec=12)
    text = page.get("text") or ""
    if "error" in page and not text:
        out["error"] = page["error"]
        return out
    out["summary"] = _bridge_summary(text)
    # vaptcha 门：正文不渲染时页面只有导航壳（首页|联系我们）
    if len(text) < 200 or ("首页" in text and "联系我们" in text and "招标" not in text and "中标" not in text):
        open_todo(
            "cebpub",
            detail_url,
            title="cebpub 详情 vaptcha 人工验证",
            note="详情页 vaptcha 挡住正文渲染；请在 Chrome「tenderfile」标签页人工过验证码一次（会话复用，后续自动抓取）。",
        )
        out["error"] = "detail_vaptcha_gated"
        return out
    attachments = _bridge_attachment_candidates(page.get("links") or [], detail_url)
    if not attachments:
        out["error"] = "no_attachment_link"
        return out
    # 下载：HTTP+页面 Cookie 优先，桥内同步 XHR 兜底
    last_err = ""
    http = HttpSession("cebpub")
    tf, err = _download_and_extract(http, "cebpub", detail_url, attachments,
                                    cookie=page.get("cookie") or "")
    if tf:
        out["ok"] = True
        out["error"] = None
        out["summary"] = _tenderfile_summary(tf["text"])
        out["tenderFile"] = tf
        return out
    if err:
        last_err = err
    session = page.get("session") or ""
    for url, fmt in attachments[:3]:
        raw, err2 = _bridge_download_b64(session, url, detail_url) if session else (None, "no_session")
        if raw is None:
            last_err = err2 or last_err
            continue
        actual = _sniff_format(raw)
        if actual is None:
            last_err = "download_failed: unrecognized content (likely a login/notice page)"
            continue
        fmt = actual
        digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:16]
        dest = TENDERFILE_DIR / "cebpub" / f"{digest}.{fmt}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        try:
            text = clean_extracted_text(extract_text(dest, fmt))
        except Exception as e:  # noqa: BLE001
            dest.unlink(missing_ok=True)
            last_err = f"extract_failed: {str(e)[:200]}"
            continue
        if not text:
            dest.unlink(missing_ok=True)
            last_err = "extract_failed: empty text"
            continue
        out["ok"] = True
        out["error"] = None
        out["summary"] = _tenderfile_summary(text)
        out["tenderFile"] = {
            "path": str(dest.relative_to(ROOT)).replace("\\", "/"),
            "text": text,
            "sourceUrl": url,
            "format": "docx" if fmt == "doc" else fmt,
        }
        return out
    out["error"] = last_err or "attachment_fetch_failed"
    return out
