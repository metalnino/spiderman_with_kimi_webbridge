"""招标文件附件抓取与正文清洗（collector/v1.2.0 tenderFile 能力，内核新模块）。

规则型 deterministic：无任何模型决策，路径死定，失败诚实返回原因，绝不造假。

各站详情现状（2026-08 探针，诚实记录）：
- ccgp：详情开放，HTTP 直取可拿正文；正文常带附件下载链接（PDF/DOC）。
- chinabidding：详情登录墙；.env CHINABIDDING_COOKIE 存在时才尝试，无 cookie 直接声明 login_wall。
- ggzy / jsggzy：详情 URL 为 www.ggzy.gov.cn 信息页；正文 JS 动态加载，静态 HTML 常无附件链接，
  尝试后无附件即如实返回 no_attachment_link。
- cebpub：详情 vaptcha + ctbpsp.com hash 路由，需浏览器会话（附件下载未接入）。
- jiangsu_zhaobiao：HTTP 521 Cloudflare/WAF，需 WebBridge（附件下载未接入）。

tenderFile 契约形状（collector/v1.2.0）：
  { "path": 下载后的文件路径（相对工作区根）,
    "text": 清洗后的正文,
    "sourceUrl": 附件原始链接（可空）,
    "format": "pdf" | "docx" | "txt"（可空） }

summary 口径：附件正文清洗后前 200 字；无附件时用详情页正文前 200 字；两者都无 → None。
"""
from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from html import unescape
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from crawl.http_session import HttpSession  # noqa: E402

TENDERFILE_DIR = ROOT / "downloads" / "tenderfiles"

# 支持 HTTP 直取详情/附件的源站（其余浏览器路由站未接入，如实跳过）
HTTP_DETAIL_SOURCES = ("ccgp", "chinabidding", "ggzy", "jsggzy")

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


def download_attachment(http: HttpSession, url: str, dest: Path, referer: str = "") -> tuple[bool, str]:
    """下载附件到 dest；返回 (ok, error)。大小超限/网络失败如实返回。"""
    try:
        headers = {}
        if referer:
            headers["Referer"] = referer
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


def fetch_tenderfile(source_id: str, detail_url: str, *, http: HttpSession | None = None) -> dict:
    """详情页 → 附件发现 → 下载 → 正文清洗。

    返回 {"ok": bool, "error": str|None, "summary": str|None,
          "tenderFile": {"path","text","sourceUrl","format"} | None}
    任何一步失败如实记录 error，tenderFile=None，绝不编造。
    """
    out: dict = {"ok": False, "error": None, "summary": None, "tenderFile": None}
    if not detail_url or not detail_url.startswith(("http://", "https://")):
        out["error"] = "no_detail_url"
        return out
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
    if source_id == "chinabidding" and ("立即注册" in html or "请先" in html):
        out["summary"] = page_summary
        out["error"] = "detail_login_wall"
        return out

    attachments = discover_attachment_urls(html, detail_url)
    if not attachments:
        out["summary"] = page_summary
        out["error"] = "no_attachment_link"
        return out

    last_err = ""
    for url, fmt in attachments[:3]:  # 最多试 3 个附件
        digest = hashlib.md5(url.encode("utf-8")).hexdigest()[:16]
        dest = TENDERFILE_DIR / source_id / f"{digest}.{fmt}"
        ok, err = download_attachment(http, url, dest, referer=detail_url)
        if not ok:
            last_err = err
            continue
        # 魔数校验：扩展名与真实格式不符时改判（防把登录页/HTML 当附件）
        raw_head = dest.read_bytes()[:2048]
        if fmt == "pdf" and not _is_pdf_magic(raw_head):
            dest.unlink(missing_ok=True)
            last_err = "download_failed: not a real pdf (magic mismatch)"
            continue
        if fmt == "docx" and not _is_zip_magic(raw_head):
            dest.unlink(missing_ok=True)
            last_err = "download_failed: not a real docx (magic mismatch)"
            continue
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
        out["ok"] = True
        out["error"] = None
        out["summary"] = _tenderfile_summary(text)
        out["tenderFile"] = {
            "path": str(dest.relative_to(ROOT)).replace("\\", "/"),
            "text": text,
            "sourceUrl": url,
            "format": fmt,
        }
        return out

    out["summary"] = page_summary
    out["error"] = last_err or "attachment_fetch_failed"
    return out
