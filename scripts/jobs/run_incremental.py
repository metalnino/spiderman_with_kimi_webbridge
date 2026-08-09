"""P0 entry: incremental crawl all enabled sources → MySQL."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from crawl.runner import run_incremental  # noqa: E402
from crawl.web_list import build_incremental_html  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--sources", type=str, default="", help="comma ids, empty=all")
    ap.add_argument("--no-list", action="store_true")
    args = ap.parse_args()
    sources = [x.strip() for x in args.sources.split(",") if x.strip()] or None
    results = run_incremental(sources=sources, max_pages=args.pages)
    out = ROOT / "data" / "web" / "last_run.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    if not args.no_list:
        path = build_incremental_html()
        print("LIST", path)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    # exit 0 even if some sources failed (observability); non-zero only if all failed
    oks = [r for r in results if r.get("status") == "success"]
    if not oks and results:
        sys.exit(2)


if __name__ == "__main__":
    main()
