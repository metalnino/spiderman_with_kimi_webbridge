"""cebpub Playwright 无头浏览器爬取（自包含，无需 Kimi 扩展；可本机/可 NAS）。

cebpub 搜索页已 JS 渲染+加密，HTTP 不可用；用浏览器渲染→填词→点搜索→抓结果。
详情用 onclick=showDetails(加密参数) 打开且需 vaptcha，故只抓列表字段(标题/发布时间/区域/平台)。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crawl.db_store import finish_run, start_run, upsert_notices  # noqa: E402
from crawl.keywords import enabled_keywords  # noqa: E402
from crawl.models import Notice  # noqa: E402

SEARCH_URL = "https://www.cebpubservice.com/ctpsp_iiss/searchbusinesstypebeforedooraction/getSearch.do"

EXTRACT_JS = r"""() => {
  const out = [];
  document.querySelectorAll("a[onclick*='showDetails']").forEach(a => {
    const row = a.closest("tr") || a.parentElement;
    out.push({title: (a.textContent || "").replace(/\s+/g, " ").trim(), row: (row && row.innerText || "").replace(/\s+/g, " ")});
  });
  return out;
}"""

SEARCH_JS = r"""(kw) => {
  const input = document.querySelector("#keySearchValue") || document.querySelector("input[name=keySearchValue]");
  if (!input) return {ok: false, error: "no_input"};
  input.value = kw;
  input.dispatchEvent(new Event("input", {bubbles: true}));
  input.dispatchEvent(new Event("change", {bubbles: true}));
  const btn = [...document.querySelectorAll("button,a,input[type=button],input[type=submit]")].find(b => /搜索|查询|检索/.test((b.textContent || b.value || "")));
  if (btn) { btn.click(); return {ok: true, method: "click"}; }
  if (typeof query === "function") { query(); return {ok: true, method: "query_fn"}; }
  return {ok: false, error: "no_trigger"};
}"""


def match_city(text: str) -> str | None:
    from crawl.config_loader import cities

    hits = [c["name"] for c in cities() if c["name"] in (text or "")]
    return hits[0] if hits else None


def extract_results(page) -> list[dict]:
    raw = page.evaluate(EXTRACT_JS) or []
    items = []
    seen = set()
    for it in raw:
        title = (it.get("title") or "").strip()
        row = it.get("row") or ""
        if len(title) < 4:
            continue
        pub = None
        dm = re.search(r"(20d{2}[-.]d{1,2}[-.]d{1,2})", row)
        if dm:
            pub = dm.group(1).replace(".", "-")
        region = None
        rm = re.search(r"【([^】]+)】", row)
        if rm:
            region = rm.group(1).strip()
        city = match_city((region or "") + " " + title)
        eid = hashlib.sha1((title + "|" + (pub or "")).encode("utf-8")).hexdigest()[:32]
        if eid in seen:
            continue
        seen.add(eid)
        items.append({"external_id": eid, "title": title, "publish_date": pub, "city": city, "region_text": region})
    return items


def main(keywords: list[str] | None = None) -> None:
    from playwright.sync_api import sync_playwright

    kws = keywords or enabled_keywords()
    run_id = start_run("cebpub")
    notices: list[Notice] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            page = browser.new_page()
            page.goto(SEARCH_URL, timeout=60000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            for kw in kws:
                page.fill("#keySearchValue", kw)
                page.wait_for_timeout(400)
                try:
                    page.locator("button:has-text('搜索'), a:has-text('搜索'), input[type=button]").first.click(timeout=5000)
                    trig = "click"
                except Exception:  # noqa: BLE001
                    trig = "click_failed"
                page.wait_for_timeout(8000)
                items = extract_results(page)
                print(f"[cebpub-pw] {kw} trig={trig} items={len(items)}", flush=True)
                for it in items:
                    notices.append(
                        Notice(
                            source_id="cebpub",
                            source_name="中国招标投标公共服务平台",
                            external_id=it["external_id"],
                            title=it["title"],
                            publish_date=it["publish_date"],
                            city=it["city"],
                            region_text=it["region_text"],
                            keyword=kw,
                            bid_status="未知",
                        )
                    )
                page.wait_for_timeout(1500)
            browser.close()
        stats = upsert_notices(notices)
        finish_run(run_id, status="success", item_count=stats["attempted"], note=f"cebpub-pw items={len(notices)}")
        print(json.dumps({"items": len(notices), **stats}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        finish_run(run_id, status="failed", item_count=0, note=str(e)[:500])
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", default="", help="comma keywords; empty=all enabled")
    args = ap.parse_args()
    kws = [k.strip() for k in args.keywords.split(",") if k.strip()] or None
    main(kws)
