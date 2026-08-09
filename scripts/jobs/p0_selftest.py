"""P0 self-test summary for docs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from db import connect  # noqa: E402
from crawl.db_store import count_notices  # noqa: E402


def main():
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, COUNT(*) AS c FROM notices GROUP BY source_id ORDER BY source_id"
            )
            by_src = cur.fetchall()
            cur.execute(
                "SELECT id, source_id, status, item_count, LEFT(note,80) AS note "
                "FROM crawl_runs ORDER BY id DESC LIMIT 8"
            )
            runs = cur.fetchall()
            cur.execute("SELECT title, source_id, city FROM notices ORDER BY created_at DESC LIMIT 5")
            samples = cur.fetchall()
    finally:
        conn.close()
    out = {
        "total": count_notices(),
        "by_source": by_src,
        "recent_runs": runs,
        "samples": samples,
        "list_html": str(ROOT / "data" / "web" / "incremental.html"),
    }
    path = ROOT / "data" / "web" / "p0_selftest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
