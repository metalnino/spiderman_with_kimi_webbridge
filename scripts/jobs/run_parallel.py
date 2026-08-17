"""并行跑多个源站（本机/手动触发）。"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from crawl.keywords import seed_keywords_from_config  # noqa: E402
from crawl.runner import run_sources_parallel  # noqa: E402
from crawl.sources import enabled_source_ids  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", default="绿植租摆")
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--sources", default="", help="comma ids; empty=all enabled")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    kws = [k.strip() for k in args.keywords.split(",") if k.strip()]
    sources = [s.strip() for s in args.sources.split(",") if s.strip()] or enabled_source_ids()
    try:
        seed_keywords_from_config()
    except Exception as e:  # noqa: BLE001
        print("seed warn:", e, flush=True)
    print(f"[parallel] sources={sources} keywords={kws} workers={args.workers}", flush=True)
    t0 = time.time()
    results = run_sources_parallel(sources, keywords=kws, max_pages=args.pages, max_workers=args.workers)
    elapsed = round(time.time() - t0, 1)
    report = {"elapsed_sec": elapsed, "sources": sources, "keywords": kws, "results": results}
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    out = ROOT / "data" / "web" / "parallel_run.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("WROTE", out)


if __name__ == "__main__":
    main()
