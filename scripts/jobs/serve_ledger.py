"""启动本机只读台账 API + UI：http://127.0.0.1:8765/"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from crawl.ledger_server import DEFAULT_HOST, DEFAULT_PORT, serve_forever  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Local readonly ledger API")
    p.add_argument("--host", default=DEFAULT_HOST, help="only localhost allowed")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = p.parse_args()
    serve_forever(args.host, args.port)


if __name__ == "__main__":
    main()
