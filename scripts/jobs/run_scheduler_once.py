from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from crawl.scheduler import run_once_and_record  # noqa: E402


def main():
    # For ops; tests mock _run_incremental
    print(json.dumps(run_once_and_record(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
