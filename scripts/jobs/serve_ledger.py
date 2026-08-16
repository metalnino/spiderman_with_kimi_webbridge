"""启动台账 API（FastAPI + uvicorn）。默认 127.0.0.1；Docker 用 LEDGER_HOST=0.0.0.0。"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import uvicorn  # noqa: E402
from crawl.api import DEFAULT_HOST, DEFAULT_PORT, app  # noqa: E402

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def main() -> None:
    p = argparse.ArgumentParser(description="Ledger API (FastAPI + uvicorn)")
    p.add_argument("--host", default=os.environ.get("LEDGER_HOST", DEFAULT_HOST))
    p.add_argument("--port", type=int, default=int(os.environ.get("LEDGER_PORT", DEFAULT_PORT)))
    args = p.parse_args()
    if args.host not in ALLOWED_HOSTS:
        raise ValueError(f"ledger bind host not allowed: {args.host} (use 127.0.0.1 or 0.0.0.0)")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
