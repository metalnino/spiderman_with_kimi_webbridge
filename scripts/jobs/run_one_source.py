"""Run a single source (for T2/T4 tests)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from crawl.runner import run_source  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "source_id",
        choices=["cebpub", "chinabidding", "ggzy", "ccgp", "jsggzy", "jiangsu_zhaobiao"],
    )
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--keywords", type=str, default="绿植租摆")
    args = ap.parse_args()
    kws = [k.strip() for k in args.keywords.split(",") if k.strip()]
    r = run_source(args.source_id, keywords=kws, max_pages=args.pages)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    sys.exit(0 if r.get("status") == "success" else 2)


if __name__ == "__main__":
    main()
