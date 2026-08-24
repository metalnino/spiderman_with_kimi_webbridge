"""工程帮（天工网，tgnet.com）—— Playwright 级源站（二级，HTTP 列表被 JS 加载/子域 SSL 不通）。

三级探路结论（2026-08 实测）：
  ① HTTP：www.tgnet.com 首页 200，但搜索结果为 JS 加载（aspx 静态 HTML 无结果）；
     bid.tgnet.com 招标子域 SSL 握手超时（本机 IP 不可达）；
  ② Playwright：search.tgnet.com/ProjectSearch.aspx?kw=<kw> 渲染后结果在 DOM
     （项目列表：标题/阶段/更新时间/链接 www.tgnet.com/project/<code>/）✓ 采用；
  ③ WebBridge：无需（二级已通）。

注意：天工网数据是「工程项目信息」（含招标阶段项目），非纯公告列表；
notice_type 取页面阶段列（如 前期立项/工程分包/已完工），如实入库。
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crawl.keywords import enabled_keywords  # noqa: E402
from crawl.models import Notice  # noqa: E402

SEARCH_URL = "https://search.tgnet.com/ProjectSearch.aspx?kw={kw}"

EXTRACT_JS = r"""() => {
  const out = [];
  document.querySelectorAll("a[href*='/project/']").forEach(a => {
    const row = a.closest("tr") || a.closest("li") || a.closest("div");
    const m = (a.getAttribute("href") || "").match(/\/project\/([A-Za-z0-9_-]+)\//);
    if (!m) return;
    const code = m[1];
    const text = (row && row.innerText || "").replace(/\s+/g, " ");
    out.push({code, title: (a.textContent || "").replace(/\s+/g, " ").trim(),
              row: text, href: a.href});
  });
  return out;
}"""


def match_city(text: str) -> Optional[str]:
    from crawl.config_loader import cities

    hits = [c["name"] for c in cities() if c["name"] in (text or "")]
    return hits[0] if hits else None


def parse_items(raw: list[dict], kw: str) -> list[Notice]:
    """DOM 行 → Notice。标题去高亮残留、取阶段/更新时间。"""
    notices: list[Notice] = []
    seen: set[str] = set()
    for it in raw or []:
        code = str((it or {}).get("code") or "")
        title = re.sub(r"<[^>]+>", "", str((it or {}).get("title") or "")).strip()
        row = str((it or {}).get("row") or "")
        href = str((it or {}).get("href") or "")
        if not code or len(title) < 4 or code in seen:
            continue
        seen.add(code)
        # 更新时间：行尾 "已完工 -- 2014-12-19" 或 "工程分包 -- 2025-12-05"
        pub = None
        dm = re.search(r"(\d{4}-\d{2}-\d{2})", row)
        if dm:
            pub = dm.group(1)
        stage = None
        sm = re.search(r"(前期立项|工程设计|工程分包|工程施工|已完工|招标|中标|其他)", row)
        if sm:
            stage = sm.group(1)
        city = match_city(row + " " + title)
        notices.append(
            Notice(
                source_id="tgnet",
                source_name="工程帮(天工网)",
                external_id=code,
                title=title,
                publish_date=pub,
                city=city,
                region_text=None,
                keyword=kw,
                notice_type=stage,
                detail_url=href or f"https://www.tgnet.com/project/{code}/",
                official_url=href or f"https://www.tgnet.com/project/{code}/",
                bid_status="未知",
            )
        )
    return notices


def main(keywords: Optional[list[str]] = None) -> dict:
    """员工外壳（collector）路由调用：返回 {status, error, notices:[dict]}。纯增量，CLI 行为不变。"""
    from dataclasses import asdict
    from urllib.parse import quote

    from playwright.sync_api import sync_playwright

    from crawl.db_store import finish_run, start_run, upsert_notices

    kws = keywords or enabled_keywords()
    run_id = start_run("tgnet")
    notices: list[Notice] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page()
            for kw in kws:
                page.goto(SEARCH_URL.format(kw=quote(kw)), timeout=60000, wait_until="domcontentloaded")
                page.wait_for_timeout(9000)
                raw = page.evaluate(EXTRACT_JS) or []
                items = parse_items(raw, kw)
                notices.extend(items)
                print(f"[tgnet-pw] {kw} items={len(items)}", flush=True)
            browser.close()
        stats = upsert_notices(notices)
        finish_run(run_id, status="success", item_count=stats["attempted"], note=f"tgnet-pw items={len(notices)}")
        return {
            "status": "success",
            "error": None,
            "notices": [{**asdict(n), "content_hash": n.content_hash()} for n in notices],
        }
    except Exception as e:  # noqa: BLE001
        finish_run(run_id, status="failed", item_count=0, note=str(e)[:500])
        return {"status": "failed", "error": str(e)[:300], "notices": []}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", default="", help="comma keywords; empty=all enabled")
    args = ap.parse_args()
    kws = [k.strip() for k in args.keywords.split(",") if k.strip()] or None
    print(json.dumps(main(kws), ensure_ascii=False, indent=2))
