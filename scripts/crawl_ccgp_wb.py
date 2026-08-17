"""CCGP via WebBridge 真浏览器（本机运行，需 Kimi 扩展连接）。
与 NAS 上 HTTP 调度互为双路径：本地 IP 被频控时 NAS HTTP 仍可用，反之亦然；
频控命中走冷却阶梯重试，仍被拦则保留已采部分结果入库（绝不丢半程数据）。
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crawl import webbridge_client as wb  # noqa: E402
from crawl.captcha_queue import open_todo  # noqa: E402
from crawl.config_loader import only_target_cities, publish_date_range, target_city_names  # noqa: E402
from crawl.db_store import finish_run, start_run, upsert_notices  # noqa: E402
from crawl.keywords import enabled_keywords  # noqa: E402
from crawl.models import Notice  # noqa: E402
from crawl.sources.ccgp import CcgpSource  # noqa: E402

SESSION = "ccgp-crawl"
SEARCH = "https://search.ccgp.gov.cn/bxsearch"

EXTRACT_JS = r"""(() => {
  const text = (document.body.innerText||'').replace(/\s+/g,' ');
  if (/访问过于频繁|频繁访问|操作频繁/.test(text + document.title)) {
    return JSON.stringify({rate_limited:true, title:document.title, textHead:text.slice(0,200)});
  }
  const totalM = text.match(/共找到\s*([\d,]+)\s*条/);
  const total = totalM ? parseInt(totalM[1].replace(/,/g,''),10) : null;
  const links = [...document.querySelectorAll('a')].filter(a => /ccgp\.gov\.cn\/cggg\//.test(a.href));
  const items = [];
  const seen = new Set();
  for (const a of links) {
    if (seen.has(a.href)) continue;
    seen.add(a.href);
    const title = (a.textContent||'').replace(/\s+/g,' ').trim();
    if (title.length < 4) continue;
    const row = a.closest('li,tr,div') || a.parentElement;
    const rowText = (row && row.innerText || '').replace(/\s+/g,' ').trim();
    const buyerM = rowText.match(/采购人[：:]\s*([^|]+)/);
    const agencyM = rowText.match(/代理机构[：:]\s*([^|]+)/);
    const timeM = rowText.match(/(20\d{2}[\.\-]\d{2}[\.\-]\d{2}\s+\d{2}:\d{2}:\d{2})/);
    items.push({
      href: a.href.replace('http://','https://'),
      title,
      buyer: buyerM ? buyerM[1].trim().slice(0,80) : null,
      agency: agencyM ? agencyM[1].trim().slice(0,80) : null,
      publish_date: timeM ? timeM[1].replace(/\./g,'-') : null,
      row_head: rowText.slice(0,400)
    });
  }
  return JSON.stringify({rate_limited:false, total, count:items.length, items:items.slice(0,40),
                         href:location.href, title:document.title});
})()"""

MOUSE_JS = r"""(() => {
  let x = 200 + Math.random() * 400, y = 200 + Math.random() * 400;
  for (let i = 0; i < 8; i++) {
    x += (Math.random() - 0.5) * 90;
    y += (Math.random() - 0.5) * 90;
    document.dispatchEvent(new MouseEvent('mousemove', {clientX: x, clientY: y, bubbles: true}));
  }
  return 'ok';
})()"""


def human_pause(min_s: float = 2.0, max_s: float = 6.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def search_url(kw: str, page: int = 1, time_type: str = "5") -> str:
    q = urllib.parse.urlencode(
        {
            "searchtype": "1",
            "page_index": str(page),
            "bidSort": "0",
            "buyerName": "",
            "projectId": "",
            "pinMu": "0",
            "bidType": "0",
            "dbselect": "bidx",
            "kw": kw,
            "timeType": time_type,
        }
    )
    return f"{SEARCH}?{q}"


def extract_results() -> dict:
    r = wb.evaluate(EXTRACT_JS, session=SESSION)
    val = (r.get("data") or {}).get("value")
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {"rate_limited": False, "items": [], "error": val[:200]}
    return val or {"rate_limited": False, "items": []}


def to_notices(items: list[dict], kw: str, cc: CcgpSource) -> list[Notice]:
    targets = set(target_city_names())
    pmin, pmax = publish_date_range()
    out: list[Notice] = []
    for it in items:
        title = (it.get("title") or "").strip()
        if len(title) < 4:
            continue
        hay = " ".join([title, it.get("row_head") or "", it.get("buyer") or ""])
        region = cc.extract_region(it.get("row_head") or "")
        city = cc.city_for(hay, region)
        pub = (it.get("publish_date") or "")[:19]
        if only_target_cities() and city not in targets:
            continue
        if pmin and pub and pub[:10] < pmin:
            continue
        if pmax and pub and pub[:10] > pmax:
            continue
        href = it.get("href") or ""
        m_id = re.search(r"t(\d+)_\d+\.htm", href)
        out.append(
            Notice(
                source_id="ccgp",
                source_name="中国政府采购网",
                external_id=str(m_id.group(1)) if m_id else href,
                title=title,
                publish_date=pub,
                city=city,
                region_text=region,
                keyword=kw,
                buyer=it.get("buyer"),
                agency=it.get("agency"),
                detail_url=href,
                official_url=href,
                bid_status="未知",
            )
        )
    return out


def fetch_keyword(kw: str, page: int, cc: CcgpSource) -> tuple[list[Notice], str | None]:
    """单词单页：频控命中走冷却阶梯重试；仍被拦返回 (partial, error)。"""
    ladder, max_retries = cc._block_cfg()
    url = search_url(kw, page)
    collected: list[Notice] = []
    for attempt in range(max_retries + 1):
        wb.navigate(url, session=SESSION, group_title="ccgp-crawl", new_tab=False)
        human_pause(2.0, 5.0)
        data = extract_results()
        if not data.get("rate_limited"):
            items = data.get("items") or []
            print(f"[ccgp-wb] {kw} p{page} -> {len(items)} total={data.get('total')}", flush=True)
            return to_notices(items, kw, cc), None
        if attempt >= max_retries:
            break
        wait = ladder[min(attempt, len(ladder) - 1)]
        print(f"[ccgp-wb] {kw} 命中频控页，冷却 {wait}s 后重试 ({attempt + 1}/{max_retries + 1})", flush=True)
        time.sleep(wait)
    return collected, f"ccgp rate_limited（WebBridge 连续 {max_retries + 1} 次被拦）"


def main(keywords: list[str] | None = None) -> None:
    kws = keywords or enabled_keywords()
    if not wb.available():
        print(json.dumps({"ok": False, "error": "webbridge_not_available", "hint": "请打开 Kimi 浏览器扩展"}, ensure_ascii=False))
        return
    cc = CcgpSource()
    run_id = start_run("ccgp")
    all_notices: list[Notice] = []
    errors: list[str] = []
    try:
        # 暖场：先访问官网首页（模拟真人入口）
        wb.navigate("https://www.ccgp.gov.cn/", session=SESSION, group_title="ccgp-crawl", new_tab=True)
        human_pause(2.0, 5.0)
        for kw in kws:
            items, err = fetch_keyword(kw, 1, cc)
            if items:
                all_notices.extend(items)
            if err:
                errors.append(err)
            human_pause(3.0, 8.0)  # 关键词之间随机停顿，防连发限流
            try:
                wb.evaluate(MOUSE_JS, session=SESSION)
            except Exception:
                pass
        stats = upsert_notices(all_notices)
        status = "success" if not errors else ("partial" if all_notices else "rate_limited")
        note = f"ccgp-wb items={len(all_notices)} errors={len(errors)} {'; '.join(errors)[:300]}"
        if errors:
            open_todo("ccgp", "source://ccgp", title="ccgp", note="; ".join(errors)[:200])
        finish_run(run_id, status=status, item_count=stats["attempted"], note=note)
        print(json.dumps({"status": status, "items": len(all_notices), **stats}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        finish_run(run_id, status="failed", item_count=0, note=str(e)[:500])
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", default="", help="comma keywords; empty=all enabled")
    args = ap.parse_args()
    kws = [k.strip() for k in args.keywords.split(",") if k.strip()] or None
    main(kws)
