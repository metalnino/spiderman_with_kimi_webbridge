"""入口：生成最简增量列表页 data/web/incremental.html"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from crawl.web_list import build_incremental_list  # noqa: E402


def main() -> None:
    out = build_incremental_list()
    print(f"WROTE {out}")


if __name__ == "__main__":
    main()
