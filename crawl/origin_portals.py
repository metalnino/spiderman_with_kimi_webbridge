"""源头平台适配层（源头追溯员第二层）—— 声明式适配器 + 通用桥驱动。

设计取舍（第一性原理）：
  - 每个源头平台长得都不一样（SPA 表格 / 静态 jhtml / 需要登录），**给每个平台写一个爬虫不可持续**；
  - 但平台之间的差异可以被压成三类声明：①检索 URL 模板 ②结果行选择器 ③详情 URL 模板；
  - 于是新增源头 = 往 config/origin_portals.json 加一条数据，代码只做「打开→取行→取 id→打开详情」这一套通用动作；
  - 拿不到适配器的平台不硬编：降级为「外部搜索引擎定位详情页 → 桥渲染」（bridge_page），仍能拿到一手正文。

所有网络动作都经 WebBridge 真浏览器（源头平台几乎都有 WAF/JS 渲染）：
  纯 HTTP 直取实测在华能平台是 412、在东部机场是 502 —— 桥是必需品，不是优化项。
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG_PATH = ROOT / "config" / "origin_portals.json"

BRIDGE_GROUP = "origin-trace"

# 结果行提取：把「选择器」注入到通用 JS 里（桥内 evaluate 在主世界执行，DOM 与 Vue 实例都可达）
_ROWS_JS = r"""(() => {
  const rows = [...document.querySelectorAll(__SEL__)];
  const out = rows.slice(0, 60).map(r => {
    const el = __TSEL__ ? r.querySelector(__TSEL__) : r;
    return {
      key: __KEY__,
      title: ((el && el.innerText) || r.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 200),
      text: (r.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 300)
    };
  });
  return JSON.stringify({href: location.href, title: document.title, count: out.length, rows: out});
})()"""

# Bing 自然结果（国内可达；不走 API key，桥内取 DOM）
_WEB_SEARCH_JS = r"""(() => {
  const out = [];
  document.querySelectorAll('#b_results > li.b_algo').forEach(li => {
    const a = li.querySelector('h2 a');
    if (!a || !a.href) return;
    out.push({title: (a.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 160),
              url: a.href,
              snippet: ((li.querySelector('.b_caption p, .b_lineclamp2, p') || {}).innerText || '').replace(/\s+/g, ' ').trim().slice(0, 240)});
  });
  return JSON.stringify({href: location.href, count: out.length, results: out.slice(0, 16),
                         blocked: /验证|verify|captcha/i.test(document.title || '')});
})()"""


def load_registry() -> dict:
    """读平台登记表；缺文件/坏 JSON 返回空表（追溯降级到外部搜索路径，不抛）。"""
    if not CFG_PATH.exists():
        return {"portals": [], "aggregatorDomains": [], "mirrorKeywords": []}
    try:
        data = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"portals": [], "aggregatorDomains": [], "mirrorKeywords": []}
    data.setdefault("portals", [])
    data.setdefault("aggregatorDomains", [])
    data.setdefault("mirrorKeywords", [])
    return data


def portals() -> list[dict]:
    return list(load_registry().get("portals") or [])


def domain_of(url: str) -> str:
    return re.sub(r"^https?://", "", (url or "")).split("/")[0].split(":")[0].lower()


def _domain_hit(host: str, suffix: str) -> bool:
    host, suffix = (host or "").lower(), (suffix or "").lower()
    return bool(host and suffix and (host == suffix or host.endswith("." + suffix)))


def match_portal(title: str, hints: dict | None = None) -> dict | None:
    """标题/线索 → 平台登记条目（buyerKeywords 命中，或线索里的域名直接命中）。"""
    hints = hints or {}
    hay = f"{title or ''} {hints.get('buyer') or ''} {hints.get('buyerShort') or ''} {hints.get('portalName') or ''}"
    best, best_len = None, 0
    for p in portals():
        for kw in p.get("buyerKeywords") or []:
            if kw and kw in hay and len(kw) > best_len:
                best, best_len = p, len(kw)
    if best:
        return best
    # 正文里出现的域名/平台名直接命中
    guess = str(hints.get("portalDomainGuess") or "")
    cand_domains = [domain_of(u) for u in (hints.get("urls") or [])] + ([domain_of(guess)] if guess else [])
    for p in portals():
        for d in p.get("domains") or []:
            if any(_domain_hit(c, d) for c in cand_domains if c):
                return p
    pname = hints.get("portalName")
    if pname:
        for p in portals():
            if p.get("name") and (p["name"] in pname or pname in p["name"]):
                return p
    return None


def classify_domain(url: str, *, registry: dict | None = None) -> str:
    """域名定性：head(主体自建) / gov(政府平台) / platform(第三方交易平台) / aggregator(我们自己的源站) / mirror(纯转载) / unknown。"""
    reg = registry or load_registry()
    host = domain_of(url)
    if not host:
        return "unknown"
    for p in reg.get("portals") or []:
        if any(_domain_hit(host, d) for d in p.get("domains") or []):
            return p.get("level") or "platform"
    for d in reg.get("aggregatorDomains") or []:
        if _domain_hit(host, d):
            return "aggregator"
    if host.endswith(".gov.cn") or host.endswith(".gov.com.cn"):
        return "gov"
    return "unknown"


def is_mirror_title(title: str, registry: dict | None = None) -> bool:
    """标题里带「XX招标网/标讯/采招网」等镜像站自报名 → 降低优先级（不是硬排除）。"""
    reg = registry or load_registry()
    t = title or ""
    return any(k in t for k in (reg.get("mirrorKeywords") or []))


# ---------------------------------------------------------------- 桥驱动 ---

def bridge_ready(wait_sec: float = 30.0) -> tuple[bool, str]:
    """桥可用性严格判定（daemon 在线 + 扩展已连接）。返回 (ok, reason)。"""
    try:
        from crawl import webbridge_client as wb

        st = wb.ensure_bridge(wait_sec=wait_sec)
    except Exception as e:  # noqa: BLE001
        return False, f"bridge_error:{type(e).__name__}"
    if not st.get("bridge"):
        return False, "bridge_daemon_down"
    if not st.get("extensions"):
        return False, "bridge_extension_disconnected"
    return True, ""


def open_page(url: str, *, source_id: str = "origin", wait_sec: float = 8.0,
              session: str | None = None, group: str = BRIDGE_GROUP) -> dict:
    """桥内打开 URL → {text, links, cookie, session, title} 或 {error}。"""
    from crawl import webbridge_client as wb
    from crawl.tenderfile import BRIDGE_EXTRACT_JS, _bridge_eval_json

    ok, why = bridge_ready()
    if not ok:
        return {"error": why}
    sess = session or f"ot-{source_id}-{hashlib.md5(url.encode('utf-8')).hexdigest()[:8]}"
    nav = wb.navigate(url, session=sess, group_title=group, new_tab=True)
    if not nav.get("ok"):
        return {"error": f"bridge_navigate_failed:{str(nav.get('error'))[:120]}", "session": sess}
    time.sleep(max(wait_sec, 1.0))
    page = _bridge_eval_json(sess, BRIDGE_EXTRACT_JS)
    # 注意：_bridge_eval_json 返回的是页面 JS 的**载荷本身**（title/len/text/links），不是 {ok:...}
    if not isinstance(page, dict) or "text" not in page:
        return {"error": f"bridge_eval_failed:{str(page)[:100]}", "session": sess}
    cookie = ""
    try:
        c = wb.export_document_cookie(sess)
        cookie = c.get("cookie") or ""
    except Exception:  # noqa: BLE001
        pass
    return {
        "error": None,
        "session": sess,
        "title": page.get("title") or "",
        "text": page.get("text") or "",
        "links": page.get("links") or [],
        "cookie": cookie,
    }


def close_tabs(group: str = BRIDGE_GROUP) -> int:
    """关掉追溯开过的 tab（防浏览器堆标签页）。"""
    try:
        from crawl import webbridge_client as wb

        return wb.close_group(group, session="origin-trace-close")
    except Exception:  # noqa: BLE001
        return 0


def search_web(query: str, *, session: str | None = None, wait_sec: float = 5.0) -> list[dict]:
    """桥内 Bing 检索 → [{title,url,snippet}]。失败/被风控返回 []。"""
    from crawl import webbridge_client as wb

    ok, _ = bridge_ready()
    if not ok:
        return []
    sess = session or "ot-websearch"
    url = "https://cn.bing.com/search?q=" + urllib.parse.quote(query)
    nav = wb.navigate(url, session=sess, group_title=BRIDGE_GROUP, new_tab=True)
    if not nav.get("ok"):
        return []
    time.sleep(max(wait_sec, 2.0))
    r = wb.evaluate(_WEB_SEARCH_JS, session=sess)
    val = ((r or {}).get("data") or {}).get("value")
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except json.JSONDecodeError:
            return []
    if not isinstance(val, dict) or val.get("blocked"):
        return []
    out = []
    for it in val.get("results") or []:
        if isinstance(it, dict) and it.get("url"):
            out.append({"title": it.get("title") or "", "url": it["url"], "snippet": it.get("snippet") or ""})
    return out


def search_portal(portal: dict, keyword: str, *, wait_sec: float | None = None) -> list[dict]:
    """按登记表的检索模板做站内检索 → [{key,title,text}]。无模板返回 []。"""
    from crawl.tenderfile import _bridge_eval_json

    sp = (portal or {}).get("search") or {}
    tmpl = sp.get("url") or ""
    if not tmpl or "{kw}" not in tmpl:
        return []
    ok, _ = bridge_ready()
    if not ok:
        return []
    url = tmpl.replace("{kw}", urllib.parse.quote(keyword))
    page = open_page(url, source_id=f"{portal.get('id')}-search",
                     wait_sec=float(wait_sec if wait_sec is not None else sp.get("waitSec") or 8))
    if page.get("error"):
        return []
    sel = sp.get("rowSelector")
    if not sel:
        return []
    js = (_ROWS_JS
          .replace("__SEL__", json.dumps(sel))
          .replace("__TSEL__", json.dumps(sp.get("rowTitleSelector") or ""))
          .replace("__KEY__", f"r.getAttribute({json.dumps(sp.get('rowKeyAttr') or 'data-row-key')}) || ''"))
    r = _bridge_eval_json(page["session"], js)
    rows = [x for x in (r.get("rows") or []) if isinstance(x, dict)]
    return rows


def detail_url_for(portal: dict, row: dict) -> str | None:
    """结果行 → 详情 URL（模板 {id}）。缺 id/模板返回 None。"""
    tmpl = ((portal or {}).get("detail") or {}).get("url") or ""
    key = str((row or {}).get("key") or "").strip()
    if tmpl and key and "{id}" in tmpl:
        return tmpl.replace("{id}", urllib.parse.quote(key))
    return None


def portal_wait(portal: dict, kind: str = "detail", default: float = 8.0) -> float:
    blk = (portal or {}).get(kind) or {}
    sp = (portal or {}).get("search") or {}
    try:
        if kind == "search":
            return float(sp.get("waitSec") or default)
        return float(blk.get("waitSec") or default)
    except (TypeError, ValueError):
        return default


def fetch_origin_page(url: str, *, portal_id: str = "origin", wait_sec: float = 10.0,
                      download: bool = True) -> dict:
    """打开源头详情页 → 一手正文 + 可下载附件（复用采集员既有附件链，不重写）。

    返回 {ok, error, text, summary, attachments:[{path,text,sourceUrl,format}], session}
    """
    from crawl.http_session import HttpSession
    from crawl.tenderfile import (
        _bridge_attachment_candidates, _bridge_summary, _download_and_extract,
    )

    page = open_page(url, source_id=portal_id, wait_sec=wait_sec)
    if page.get("error"):
        return {"ok": False, "error": page["error"], "text": "", "summary": None, "attachments": []}
    text = page.get("text") or ""
    if len(text) < 120:
        return {"ok": False, "error": "origin_page_empty", "text": text, "summary": None, "attachments": []}
    out: dict = {"ok": True, "error": None, "text": text, "summary": _bridge_summary(text),
                 "pageTitle": page.get("title") or "", "attachments": [], "session": page.get("session")}
    if not download:
        return out
    atts = _bridge_attachment_candidates(page.get("links") or [], url)
    if not atts:
        return out
    http = HttpSession("origin")
    tf, err = _download_and_extract(http, f"origin/{portal_id}", url, atts, cookie=page.get("cookie") or "")
    if tf:
        out["attachments"] = [tf]
    else:
        out["attachmentError"] = err or "attachment_fetch_failed"
        out["attachmentCandidates"] = [u for u, _ in atts]
    return out
