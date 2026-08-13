from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect  # noqa: E402


def open_todo(source_id: str, detail_url: str, title: str | None = None, note: str | None = None) -> int:
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            # 幂等：同一 source+url 已有 open 待办则复用，避免 cebpub 每轮累积重复待办
            cur.execute(
                "SELECT id FROM captcha_todos WHERE source_id=%s AND detail_url=%s AND status='open' LIMIT 1",
                (source_id, detail_url),
            )
            row = cur.fetchone()
            if row:
                return int(row["id"])
            cur.execute(
                "INSERT INTO captcha_todos (source_id, detail_url, title, status, note) "
                "VALUES (%s,%s,%s,'open',%s)",
                (source_id, detail_url, title, note),
            )
            return int(cur.lastrowid)
    finally:
        conn.close()


def close_todo(todo_id: int, note: str | None = None) -> bool:
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE captcha_todos SET status='closed', closed_at=%s, note=COALESCE(%s, note) "
                "WHERE id=%s AND status='open'",
                (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), note, todo_id),
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def list_open(limit: int = 50) -> list[dict]:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, source_id, detail_url, title, status, note, created_at "
                "FROM captcha_todos WHERE status='open' ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            return list(cur.fetchall())
    finally:
        conn.close()
