"""只读探针：公告里「检索词不在标题中」的比例（解释为何无关键词高亮）。"""
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
                "SELECT COUNT(*) AS total, "
                "SUM(CASE WHEN keyword IS NOT NULL AND LOCATE(keyword, title) > 0 THEN 1 ELSE 0 END) AS in_title, "
                "SUM(CASE WHEN keyword IS NOT NULL AND LOCATE(keyword, title) = 0 THEN 1 ELSE 0 END) AS not_in_title, "
                "SUM(keyword IS NULL) AS no_kw "
                "FROM notices"
            )
            tot = dict(cur.fetchone())
            cur.execute(
                "SELECT keyword, COUNT(*) AS c, SUM(LOCATE(keyword, title) > 0) AS in_title "
                "FROM notices WHERE keyword IS NOT NULL GROUP BY keyword ORDER BY c DESC LIMIT 60"
            )
            rows = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT COUNT(*) AS c FROM notices WHERE clean_status='pass'")
            p = cur.fetchone()["c"]
    finally:
        conn.close()
    out = {"total": tot, "clean_pass": p, "per_keyword": rows}
    (ROOT / "data" / "kw_highlight_probe.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({"total": tot, "clean_pass": p}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
