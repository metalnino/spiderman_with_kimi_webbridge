"""Apply ops tables/columns for P1/P2 (compatible with MySQL 8.0.28)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect, load_env  # noqa: E402


def column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        (load_env()["MYSQL_DATABASE"], table, column),
    )
    return cur.fetchone() is not None


def main():
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            for col, ddl in [
                ("clean_status", "ALTER TABLE notices ADD COLUMN clean_status VARCHAR(32) NULL"),
                ("clean_reason", "ALTER TABLE notices ADD COLUMN clean_reason VARCHAR(255) NULL"),
                ("manual_label", "ALTER TABLE notices ADD COLUMN manual_label VARCHAR(32) NULL"),
            ]:
                if not column_exists(cur, "notices", col):
                    cur.execute(ddl)
                    print("ADD", col)
                else:
                    print("SKIP", col)
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS clean_events (
                  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                  notice_id BIGINT UNSIGNED NULL,
                  title VARCHAR(512) NOT NULL,
                  source_id VARCHAR(32) NULL,
                  decision VARCHAR(32) NOT NULL,
                  reason VARCHAR(255) NULL,
                  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  PRIMARY KEY (id),
                  KEY idx_decision (decision),
                  KEY idx_created (created_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS captcha_todos (
                  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                  source_id VARCHAR(32) NOT NULL,
                  detail_url VARCHAR(1024) NOT NULL,
                  title VARCHAR(512) NULL,
                  status VARCHAR(32) NOT NULL DEFAULT 'open',
                  note VARCHAR(512) NULL,
                  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                  closed_at DATETIME NULL,
                  PRIMARY KEY (id),
                  KEY idx_status (status)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS keyword_state (
                  keyword VARCHAR(64) NOT NULL,
                  enabled TINYINT(1) NOT NULL DEFAULT 1,
                  group_name VARCHAR(32) NULL,
                  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                  PRIMARY KEY (keyword)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """
            )
            print("OK tables")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
