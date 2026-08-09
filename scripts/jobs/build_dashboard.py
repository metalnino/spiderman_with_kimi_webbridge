from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from crawl.dashboard import build_dashboard  # noqa: E402


def main():
    path = build_dashboard()
    print("WROTE", path)


if __name__ == "__main__":
    main()
