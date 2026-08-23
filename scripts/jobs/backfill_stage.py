"""P4 存量回填：为已入库公告重算 notice_stage / stage_rank / project_key / project_name。

幂等：可重复跑；--all 强制全量重算（默认只补 NULL 行）。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from db import connect  # noqa: E402
from crawl.stage import classify_stage, project_key  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Backfill notice stage / project key")
    p.add_argument("--all", action="store_true", help="recompute all rows (default: only NULL)")
    args = p.parse_args()

    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            where = "1=1" if args.all else "(notice_stage IS NULL OR project_key IS NULL)"
            cur.execute(f"SELECT id, title, city, notice_type FROM notices WHERE {where}")
            rows = cur.fetchall()
            done = 0
            for r in rows:
                stage, rank = classify_stage(r["title"], r["notice_type"])
                pkey, core = project_key(r["title"], r["city"])
                cur.execute(
                    "UPDATE notices SET notice_stage=%s, stage_rank=%s, project_key=%s, project_name=%s WHERE id=%s",
                    (stage, rank, pkey, (core[:500] if core else None), r["id"]),
                )
                done += 1
            print(f"backfilled {done} rows ({'all' if args.all else 'NULL only'})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
