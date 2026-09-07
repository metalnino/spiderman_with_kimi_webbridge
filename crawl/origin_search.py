"""原发站站内检索（ggzy 全国公共资源交易平台）。

穿透思路：聚合站（chinabidding/cebpub）登录墙后的核心字段（采购人/金额/中标），
在原发平台 ggzy 上是开放的。这里提供：
  1. search_keyword(title)：从公告标题提取 ggzy 检索词（去阶段词/日期的核心名）。
  2. search_ggzy(keyword)：调 ggzy getTradList 检索，返回 [{title,url,publishTime,id}]。
  3. match_ggzy(title, results)：按标题字符重叠率找最匹配的一条。

纯规则、可单测（search_ggzy 的 HTTP 层可 mock）。
"""
from __future__ import annotations

import re
import urllib.parse

GGZY_SEARCH_API = "https://www.ggzy.gov.cn/information/pubTradingInfo/getTradList"


def search_keyword(title: str) -> str:
    """公告标题 → ggzy 检索词：取 project_core 核心名（去阶段词/日期/标点），截断 20 字。"""
    from crawl.stage import project_core

    core = project_core(title or "")
    if not core:
        core = re.sub(r"[\s（）()【】\[\]{}：:，,。.、/\\\-—–_+|·《》\"'“”]+", "", title or "")[:12]
    return core[:20]


def search_ggzy(keyword: str, *, max_results: int = 5) -> list[dict]:
    """ggzy 站内检索。返回 [{title, url, publishTime, id}]；失败/无结果返回 []。"""
    from crawl.http_session import HttpSession

    http = HttpSession("ggzy")
    body = urllib.parse.urlencode({"FINDTXT": keyword, "PAGENUMBER": "1", "DEAL_TIME": "05"}).encode()
    try:
        data = http.get_json(
            GGZY_SEARCH_API,
            data=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://www.ggzy.gov.cn/deal/dealList.html",
                "Origin": "https://www.ggzy.gov.cn",
            },
        )
    except Exception:
        return []
    if not isinstance(data, dict) or data.get("code") != 200:
        return []
    recs = ((data.get("data") or {}).get("records")) or []
    out: list[dict] = []
    for rec in recs[:max_results]:
        href = rec.get("url") or ""
        url = ("https://www.ggzy.gov.cn" + href) if str(href).startswith("/") else str(href)
        out.append({
            "title": rec.get("title") or "",
            "url": url,
            "publishTime": rec.get("publishTime"),
            "id": str(rec.get("id") or ""),
        })
    return out


def match_ggzy(title: str, results: list[dict]) -> dict | None:
    """在 ggzy 检索结果里找与目标标题最匹配的一条（核心名字符重叠率 ≥ 0.5）。"""
    from crawl.stage import project_core

    t_core = project_core(title or "")
    if not t_core:
        return None
    t_set = set(t_core)
    best, best_score = None, 0.0
    for r in results or []:
        r_core = project_core(r.get("title") or "")
        if not r_core:
            continue
        overlap = len(t_set & set(r_core))
        score = overlap / max(1, len(t_set))
        if score > best_score:
            best, best_score = r, score
    return best if (best and best_score >= 0.5) else None
