"""P5 原发寻址：从聚合站转载信息定位原始发布来源。

一期能力（deterministic，不追求长尾全覆盖，找不到如实返回空）：
1. 正文来源行解析：详情/摘要文本中的「信息来源/发布媒介/来源网站…」行 → 单位名/URL。
2. 主体→原发平台映射：config/origin_platforms.json（高频主体关键词 → 平台域名；已验证再入库）。
3. 已知 HTTP 直取域：ccgp/ggzy/江苏省交易中心域的原发链接可复用既有详情能力回填。

样例文本：
  「…信息来源: 中国政府采购网 http://www.ccgp.gov.cn …」
  「发布媒介：招商局集团电子招标采购交易平台」
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG_PATH = ROOT / "config" / "origin_platforms.json"

# 来源行：标签 + 冒号 + 内容（到换行/分号/竖线为止）
# 裸「来源」需负向断言排除「资金来源」等误命中
_ORIGIN_LINE_RE = re.compile(
    r"(?:信息来源|信息发布媒体|发布媒介|来源网站|来源媒体|发布媒体|公告来源|来源平台|信息来源平台|发布平台|(?<![资金])来源)"
    r"\s*[:：]?\s*([^\n|;；]{2,200})",
    re.I,
)
_URL_RE = re.compile(r"https?://[^\s\"'<>）)】\]，,；;]+", re.I)

# 来源行内的噪声切分点（页面文本常被压成一行，来源名后面紧跟阅读次数/打印等控件文本；容忍词间空白）
_NOISE_SPLIT_RE = re.compile(
    r"阅\s*读\s*[次数量]|浏\s*览\s*[次数量]|打\s*印|关\s*闭|原文链接|项目ID|发布日期|附\s*件|下\s*载",
    re.I,
)

# 原发转爬路由配置（config/origin_fetch_routes.json）；缺配置时兜底
ROUTES_PATH = ROOT / "config" / "origin_fetch_routes.json"
_DEFAULT_ROUTES = [
    {"suffix": "ccgp.gov.cn", "mode": "ccgp_http"},
    {"suffix": "ggzy.gov.cn", "mode": "ggzy_http"},
    {"suffix": "jszwfw.gov.cn", "mode": "ggzy_http"},
]


def _routes() -> list[dict]:
    if ROUTES_PATH.exists():
        try:
            data = json.loads(ROUTES_PATH.read_text(encoding="utf-8"))
            if isinstance(data.get("routes"), list):
                return data["routes"]
        except (OSError, json.JSONDecodeError):
            pass
    return _DEFAULT_ROUTES


def _host(url: str) -> str:
    return re.sub(r"^https?://", "", (url or "")).split("/")[0].lower()


def fetch_route_for(url: str) -> str | None:
    """原发 URL → 抓取模式（ccgp_http / ggzy_http）；不可直取返回 None。"""
    host = _host(url)
    if not host:
        return None
    for r in _routes():
        suf = str(r.get("suffix") or "")
        if suf and (host == suf or host.endswith("." + suf)):
            return str(r.get("mode"))
    # ccgp 区域站点（www.ccgp-jiangsu.gov.cn 等）与中央同平台、同详情结构
    if "ccgp-" in host and host.endswith(".gov.cn"):
        return "ccgp_http"
    return None


def origin_lines(text: str) -> list[str]:
    """提取所有来源行的内容片段（去首尾空白、在噪声词处截断）。"""
    out: list[str] = []
    for m in _ORIGIN_LINE_RE.finditer(text or ""):
        frag = _NOISE_SPLIT_RE.split(m.group(1))[0].strip(" :：,，。.、\t")
        if frag:
            out.append(frag)
    return out


def origin_url(text: str) -> str | None:
    """来源片段/正文里第一个 http(s) 链接；没有返回 None。"""
    m = _URL_RE.search(text or "")
    return m.group(0).rstrip(".,;:") if m else None


def origin_entity(text: str) -> str | None:
    """来源片段里的单位/平台名（剥掉 URL 与括号后的剩余文本）。"""
    for line in origin_lines(text):
        rest = _URL_RE.sub(" ", line)
        rest = re.sub(r"[()（）【】\[\]]", " ", rest)
        rest = rest.strip(" :：,，。.、")
        rest = re.sub(r"\s+", " ", rest).strip()
        if len(rest) >= 4:
            return rest
    return None


def platform_map() -> list[dict]:
    """主体→原发平台映射表（config/origin_platforms.json，可维护）。"""
    if not CFG_PATH.exists():
        return []
    try:
        cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return cfg.get("platforms") or []


def match_entity_map(title: str, entity: str | None = None) -> dict | None:
    """标题或来源单位命中映射表 → 返回平台条目。"""
    hay = f"{title or ''} {entity or ''}"
    best = None
    for p in platform_map():
        for kw in p.get("keywords") or []:
            if kw and kw in hay:
                # 长关键词优先（更具体的主体）
                if best is None or len(kw) > best[1]:
                    best = (p, len(kw))
    return best[0] if best else None


def is_http_fetchable(url: str) -> bool:
    """是否可 HTTP 直取（兼容旧调用；等价 fetch_route_for(url) is not None）。"""
    return fetch_route_for(url) is not None


def resolve_origin(title: str, summary_text: str | None) -> dict:
    """聚合站公告 → 原发线索。返回 {"url","entity","platform","note"}，找不到返回 {}。"""
    text = summary_text or ""
    url = origin_url(text)
    entity = origin_entity(text)
    mapped = match_entity_map(title, entity)
    note_parts: list[str] = []
    if mapped:
        note_parts.append(f"主体映射:{mapped.get('name')}")
    if entity and not url:
        note_parts.append(f"来源单位:{entity}")
    out: dict = {"url": url, "entity": entity, "platform": mapped, "note": "；".join(note_parts) or None}
    if not url and mapped:
        out["url"] = f"https://{mapped['domain']}/"  # 映射命中但正文无链接：给平台首页（供人工/后续站内搜索）
        out["note"] = (out["note"] or "") + "（平台首页，站内检索待接入）"
    if not out.get("url") and not mapped and not entity:
        return {}
    return out
