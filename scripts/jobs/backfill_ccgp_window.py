"""P7 ccgp 全窗口回溯扫描（HTTP 路径；被频控时用桥路径 scripts/crawl_ccgp_wb.py --start/--end）。

实测结论（2026-08-24，桥探针）：ccgp 自定义时间参数（start_time/end_time 任意格式、
timeType 1~6）服务端均不按参数过滤；「绿植租摆」近半年（timeType=5）窗口总量仅 27 条（2 页）。
因此回溯 = timeType=5 多页扫全窗口 + 客户端按发布窗口过滤（本作业），
页深直到空/水位边界。断点=水位本身（重跑幂等）。

用法：
  python scripts/jobs/backfill_ccgp_window.py [--max-pages 8]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from crawl.config_loader import only_target_cities, publish_date_range, target_city_names  # noqa: E402
from crawl.db_store import upsert_notices  # noqa: E402
from crawl.sources.ccgp import CcgpSource  # noqa: E402
from crawl import watermark  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ccgp 全窗口回溯扫描（timeType=5 多页 + 客户端过滤）")
    ap.add_argument("--max-pages", type=int, default=8)
    ap.add_argument("--kw", default="绿植租摆")
    args = ap.parse_args(argv)

    cap = args.max_pages
    if os.environ.get("SPIDER_CCGP_MAX_PAGES"):
        cap = int(os.environ["SPIDER_CCGP_MAX_PAGES"])
    src = CcgpSource()
    wm = watermark.load("ccgp")
    targets = set(target_city_names()) if only_target_cities() else None
    pmin, pmax = publish_date_range()
    total_raw = total_kept = 0
    for page in range(1, cap + 1):
        print(f"[backfill] page={page} ...", flush=True)
        try:
            raw_page = list(src._parse(src._fetch_page(_page_url(args.kw, page), []), args.kw))
        except Exception as e:  # noqa: BLE001 —— 频控/网络如实停（重跑幂等）
            print(f"[backfill] page={page} FAILED: {e}", flush=True)
            return 1
        total_raw += len(raw_page)
        page_kept = list(raw_page)
        if targets:
            page_kept = [n for n in page_kept if (n.city or "") in targets]
        if pmin or pmax:
            page_kept = [n for n in page_kept
                         if (not n.publish_date
                             or (not pmin or str(n.publish_date)[:10] >= pmin)
                             and (not pmax or str(n.publish_date)[:10] <= pmax))]
        if page_kept:
            stats = upsert_notices(page_kept)
            total_kept += len(page_kept)
            print(f"[backfill] page={page} kept={len(page_kept)} (upsert≈{stats['affected']})", flush=True)
        if not raw_page:
            break  # 空页即结果尽
        if all(n.external_id in wm for n in raw_page):
            break  # 水位边界：整页原始已见 → 更深页更旧，停
    print(f"[backfill] DONE raw={total_raw} kept={total_kept}", flush=True)
    return 0


def _page_url(kw: str, page: int) -> str:
    import urllib.parse

    q = urllib.parse.urlencode(
        {
            "searchtype": "1", "page_index": str(page), "bidSort": "0",
            "buyerName": "", "projectId": "", "pinMu": "0", "bidType": "0",
            "dbselect": "bidx", "kw": kw, "timeType": "5",
        }
    )
    return "https://search.ccgp.gov.cn/bxsearch?" + q


if __name__ == "__main__":
    sys.exit(main())
