"""本机同事划码：list / open / done。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from crawl.captcha_flow import list_open_detailed, open_for_human, resolve_todo  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Local human captcha solve helpers")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="list open todos")
    p_list.add_argument("--limit", type=int, default=30)

    p_open = sub.add_parser("open", help="open todo in WebBridge/browser")
    p_open.add_argument("--id", type=int, required=True)

    p_done = sub.add_parser("done", help="export cookie + close todo")
    p_done.add_argument("--id", type=int, required=True)
    p_done.add_argument("--cookie", default=None, help="optional Cookie header paste")
    p_done.add_argument("--note", default=None)

    args = ap.parse_args()
    if args.cmd == "list":
        rows = list_open_detailed(limit=args.limit)
        print(json.dumps(rows, ensure_ascii=False, indent=2, default=str))
        return
    if args.cmd == "open":
        print(json.dumps(open_for_human(args.id), ensure_ascii=False, indent=2, default=str))
        return
    if args.cmd == "done":
        print(
            json.dumps(
                resolve_todo(args.id, cookie_header=args.cookie, note=args.note),
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )


if __name__ == "__main__":
    main()
