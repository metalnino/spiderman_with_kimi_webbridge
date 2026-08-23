"""P4 详情字段批量回填（存量跑批，复用 crawl.backfill.backfill_notice）。

用法：
  python scripts/jobs/backfill_details.py --source chinabidding --limit 20
  python scripts/jobs/backfill_details.py --source ccgp --limit 50
失败（登录墙/频控/解析空）如实写入 notices.detail_status，不重试轰炸。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from db import connect  # noqa: E402
from crawl.backfill import backfill_notice  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Backfill detail fields for one source")
    p.add_argument("--source", required=True, help="ccgp / chinabidding / jiangsu_zhaobiao / cebpub / ggzy / jsggzy")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--delay", type=float, default=3.0, help="条间冷却秒数")
    args = p.parse_args()

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM notices WHERE source_id=%s AND amount IS NULL AND buyer IS NULL "
                "AND detail_url IS NOT NULL ORDER BY created_at DESC LIMIT %s",
                (args.source, args.limit),
            )
            ids = [r["id"] for r in cur.fetchall()]
    finally:
        conn.close()

    if not ids:
        print("no candidates")
        return
    ok = fail = 0
    for i, nid in enumerate(ids):
        out = backfill_notice(nid)
        if out.get("ok"):
            ok += 1
            print(f"[{i+1}/{len(ids)}] id={nid} ok {out.get('fields') or out.get('summary', '')[:40]}")
        else:
            fail += 1
            print(f"[{i+1}/{len(ids)}] id={nid} ERR {str(out.get('error'))[:60]}")
        if i < len(ids) - 1 and args.delay > 0:
            time.sleep(args.delay)
    print(f"done ok={ok} fail={fail}")


if __name__ == "__main__":
    main()
