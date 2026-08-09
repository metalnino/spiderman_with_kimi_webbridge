from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from crawl.keywords import seed_keywords_from_config, set_keyword_enabled  # noqa: E402


def main():
    n = seed_keywords_from_config()
    print("seeded", n)
    # demo disable/enable API used by tests
    if n:
        pass


if __name__ == "__main__":
    main()
