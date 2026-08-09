"""Create spiderman_bids database + tables (utf8mb4)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from db import connect, load_env, ping  # noqa: E402


def main():
    info = ping()
    print("PING", info)
    cfg = load_env()
    schema = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    # split statements carefully; keep USE / CREATE
    stmts = []
    buf = []
    for line in schema.splitlines():
        if line.strip().startswith("--"):
            continue
        buf.append(line)
        if line.rstrip().endswith(";"):
            stmts.append("\n".join(buf).strip())
            buf = []
    if buf:
        stmts.append("\n".join(buf).strip())

    conn = connect(use_env_db=False, autocommit=True)
    try:
        with conn.cursor() as cur:
            for s in stmts:
                if not s:
                    continue
                cur.execute(s)
                print("OK", s.split("\n", 1)[0][:80])
            cur.execute(
                "SELECT DEFAULT_CHARACTER_SET_NAME AS cs, DEFAULT_COLLATION_NAME AS cl "
                "FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=%s",
                (cfg["MYSQL_DATABASE"],),
            )
            print("DB_CHARSET", cur.fetchone())
            cur.execute(
                "SELECT TABLE_NAME, TABLE_COLLATION FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=%s ORDER BY TABLE_NAME",
                (cfg["MYSQL_DATABASE"],),
            )
            for row in cur.fetchall():
                print("TABLE", row["TABLE_NAME"], row["TABLE_COLLATION"])
            # chinese smoke test
            cur.execute(f"USE `{cfg['MYSQL_DATABASE']}`")
            cur.execute(
                "INSERT INTO notices (source_id, source_name, external_id, title, content_hash) "
                "VALUES (%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE title=VALUES(title)",
                ("smoke", "连通测试", "smoke-1", "绿植租摆中文测试", "smokehash000000000000000000000000000001"),
            )
            cur.execute("SELECT title FROM notices WHERE external_id=%s", ("smoke-1",))
            print("CN_OK", cur.fetchone())
            cur.execute("DELETE FROM notices WHERE external_id=%s", ("smoke-1",))
    finally:
        conn.close()
    print("DONE", cfg["MYSQL_DATABASE"])


if __name__ == "__main__":
    main()
