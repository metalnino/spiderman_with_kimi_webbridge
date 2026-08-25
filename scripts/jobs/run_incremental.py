"""P0 entry: incremental crawl all enabled sources → MySQL."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from crawl.dashboard import build_dashboard  # noqa: E402
from crawl.keywords import seed_keywords_from_config  # noqa: E402
from crawl import mail_report  # noqa: E402
from crawl.runner import run_incremental  # noqa: E402
from crawl.web_list import build_incremental_list  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--sources", type=str, default="", help="comma ids, empty=all")
    ap.add_argument("--no-list", action="store_true")
    args = ap.parse_args()
    try:
        seed_keywords_from_config()
    except Exception as e:  # noqa: BLE001
        print("seed_keywords_warn", e, flush=True)
    # 完成钩子水位：跑前记录 DB 端最新 created_at，跑后据此取「本轮真正新增」（服务器时钟，无漂移）。
    watermark = None
    try:
        watermark = mail_report.last_watermark()
    except Exception as e:  # noqa: BLE001
        print("mail_watermark_warn", e, flush=True)
    sources = [x.strip() for x in args.sources.split(",") if x.strip()] or None
    results = run_incremental(sources=sources, max_pages=args.pages)
    out = ROOT / "data" / "web" / "last_run.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.no_list:
        print("LIST", build_incremental_list())
        print("DASHBOARD", build_dashboard())
    print(json.dumps(results, ensure_ascii=False, indent=2))
    # 完成钩子：任务跑完自动给 QQ 邮箱发增量简报（HTML）。SPIDER_NO_EMAIL=1 关闭；失败只记录不挡主流程。
    try:
        mr = mail_report.send_from_http(results, watermark)
        print("[mail]", json.dumps(mr, ensure_ascii=False), flush=True)
    except Exception as e:  # noqa: BLE001
        print("[mail] error", f"{type(e).__name__}: {e}", flush=True)
    oks = [r for r in results if r.get("status") == "success"]
    if not oks and results:
        sys.exit(2)


if __name__ == "__main__":
    main()
