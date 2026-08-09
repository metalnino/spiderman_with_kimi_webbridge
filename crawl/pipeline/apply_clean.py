from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect  # noqa: E402

from crawl.ai_hooks import classify_relevance
from crawl.pipeline.clean import clean_notice


def refresh_clean_status(limit: int = 5000) -> dict:
    conn = connect(autocommit=True)
    stats = {"pass": 0, "drop": 0, "review": 0}
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, source_id, manual_label FROM notices "
                "ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            rows = cur.fetchall()
            for r in rows:
                # manual / AI-hook (defaults to rules)
                if r.get("manual_label"):
                    res = clean_notice(r["title"], r.get("manual_label"))
                else:
                    res = classify_relevance(r["title"] or "")
                stats[res.decision] = stats.get(res.decision, 0) + 1
                cur.execute(
                    "UPDATE notices SET clean_status=%s, clean_reason=%s WHERE id=%s",
                    (res.decision, res.reason[:255], r["id"]),
                )
                cur.execute(
                    "INSERT INTO clean_events (notice_id, title, source_id, decision, reason) "
                    "VALUES (%s,%s,%s,%s,%s)",
                    (r["id"], (r["title"] or "")[:512], r.get("source_id"), res.decision, res.reason[:255]),
                )
    finally:
        conn.close()
    return stats


def set_manual_label(notice_id: int, label: str) -> None:
    assert label in {"relevant", "irrelevant", "followed"}
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE notices SET manual_label=%s WHERE id=%s", (label, notice_id))
            cur.execute("SELECT title, source_id FROM notices WHERE id=%s", (notice_id,))
            row = cur.fetchone()
            res = clean_notice(row["title"], label)
            cur.execute(
                "UPDATE notices SET clean_status=%s, clean_reason=%s WHERE id=%s",
                (res.decision, res.reason, notice_id),
            )
            cur.execute(
                "INSERT INTO clean_events (notice_id, title, source_id, decision, reason) "
                "VALUES (%s,%s,%s,%s,%s)",
                (notice_id, row["title"], row["source_id"], res.decision, res.reason),
            )
    finally:
        conn.close()
