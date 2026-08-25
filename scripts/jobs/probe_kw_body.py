"""只读探针：正文(summary)回填覆盖率 + 检索词在正文的命中情况。"""
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
                "SUM(summary IS NOT NULL AND summary <> '') AS has_summary "
                "FROM notices"
            )
            t = dict(cur.fetchone())
            cur.execute(
                "SELECT COUNT(*) AS body_matched, "
                "SUM(LOCATE(keyword, summary) > 0) AS kw_in_summary "
                "FROM notices "
                "WHERE keyword IS NOT NULL AND LOCATE(keyword, title) = 0 "
                "AND summary IS NOT NULL AND summary <> ''"
            )
            b = dict(cur.fetchone())
            cur.execute(
                "SELECT COUNT(*) AS body_matched_all FROM notices "
                "WHERE keyword IS NOT NULL AND LOCATE(keyword, title) = 0"
            )
            ba = dict(cur.fetchone())
            # 按源站看 summary 覆盖率（正文命中徽标能否点亮的关键）
            cur.execute(
                "SELECT source_id, COUNT(*) AS c, "
                "SUM(summary IS NOT NULL AND summary <> '') AS has_summary "
                "FROM notices GROUP BY source_id ORDER BY c DESC"
            )
            by_src = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    out = {"total": t, "body_matched": b, "body_matched_all": ba, "by_source": by_src}
    (ROOT / "data" / "kw_body_probe.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(json.dumps({"total": t, "body_matched": b, "body_matched_all": ba}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
