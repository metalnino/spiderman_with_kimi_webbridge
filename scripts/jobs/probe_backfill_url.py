"""只读探针：各源站 notice 的 detail_url 覆盖情况（判断回填路由是否可落地）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect  # noqa: E402


def main() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_id, COUNT(*) AS c, "
                "SUM(detail_url IS NOT NULL AND detail_url <> '') AS has_detail, "
                "SUM(official_url IS NOT NULL AND official_url <> '') AS has_official "
                "FROM notices GROUP BY source_id ORDER BY c DESC"
            )
            rows = [dict(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT id, source_id, title, detail_url, official_url FROM notices "
                "WHERE source_id IN ('yfbzb','qianlima','tgnet') "
                "AND (detail_url IS NOT NULL AND detail_url <> '') LIMIT 9"
            )
            samples = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    out = {"by_source": rows, "samples": samples}
    (ROOT / "data" / "backfill_url_probe.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps(out, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
