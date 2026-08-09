"""Run ccgp + ggzy + chinabidding trial crawls and merge summary."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "trial_multi"
SCRIPTS = [
    "crawl_ccgp_wb.py",  # HTTP 易频控，默认走 WebBridge
    "crawl_ggzy.py",
    "crawl_chinabidding.py",
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    for name in SCRIPTS:
        print("=" * 60, flush=True)
        print("RUN", name, flush=True)
        p = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / name)],
            cwd=str(ROOT / "scripts"),
        )
        results[name] = {"exit_code": p.returncode}

    merged = {"sources": {}}
    for key in ("ccgp", "ggzy", "chinabidding"):
        sp = OUT / f"{key}_summary.json"
        if sp.exists():
            merged["sources"][key] = json.loads(sp.read_text(encoding="utf-8"))
    # light merge of items counts
    all_items = []
    for key in ("ccgp", "ggzy", "chinabidding"):
        ip = OUT / f"{key}_items.json"
        if ip.exists():
            items = json.loads(ip.read_text(encoding="utf-8"))
            all_items.extend(items)
    merged["totals"] = {
        "items": len(all_items),
        "by_source": {
            k: (merged["sources"].get(k) or {}).get("list_items", 0)
            for k in ("ccgp", "ggzy", "chinabidding")
        },
        "script_exits": results,
    }
    (OUT / "multi_summary.json").write_text(
        json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("=" * 60)
    print(json.dumps(merged["totals"], ensure_ascii=False, indent=2))
    print("WROTE", OUT / "multi_summary.json")


if __name__ == "__main__":
    main()
