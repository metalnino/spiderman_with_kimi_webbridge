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


def index_exists(cur, table: str, index: str) -> bool:
    cur.execute(
        "SELECT 1 FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND INDEX_NAME=%s LIMIT 1",
        (load_env()["MYSQL_DATABASE"], table, index),
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
                ("read_at", "ALTER TABLE notices ADD COLUMN read_at DATETIME NULL"),
                ("lead_status", "ALTER TABLE notices ADD COLUMN lead_status VARCHAR(32) NOT NULL DEFAULT '待处理'"),
                ("amount_status", "ALTER TABLE notices ADD COLUMN amount_status VARCHAR(32) NULL"),
                ("remark", "ALTER TABLE notices ADD COLUMN remark VARCHAR(512) NULL"),
                # P4：阶段 / 时间线 / 详情回填
                ("notice_stage", "ALTER TABLE notices ADD COLUMN notice_stage VARCHAR(32) NULL COMMENT '阶段: intent/bidding/change/preselect/opening/candidate/result/terminated/other'"),
                ("stage_rank", "ALTER TABLE notices ADD COLUMN stage_rank TINYINT UNSIGNED NULL COMMENT '时间线顺序'"),
                ("project_key", "ALTER TABLE notices ADD COLUMN project_key CHAR(40) NULL COMMENT '项目时间线键 sha1(city|core)'"),
                ("project_name", "ALTER TABLE notices ADD COLUMN project_name VARCHAR(512) NULL COMMENT '核心项目名（展示/调试）'"),
                ("summary", "ALTER TABLE notices ADD COLUMN summary TEXT NULL COMMENT '详情正文摘要（回填）'"),
                ("tenderfile_path", "ALTER TABLE notices ADD COLUMN tenderfile_path VARCHAR(512) NULL COMMENT '附件落盘路径（回填）'"),
                ("detail_status", "ALTER TABLE notices ADD COLUMN detail_status VARCHAR(32) NULL COMMENT '最近一次回填状态'"),
                # P5：原发寻址
                ("original_url", "ALTER TABLE notices ADD COLUMN original_url VARCHAR(1024) NULL COMMENT '原发站链接（转载行寻址结果）'"),
                ("origin_source", "ALTER TABLE notices ADD COLUMN origin_source VARCHAR(128) NULL COMMENT '原发来源（平台/单位名）'"),
            ]:
                if not column_exists(cur, "notices", col):
                    cur.execute(ddl)
                    print("ADD", col)
                else:
                    print("SKIP", col)
            for idx, ddl in [
                ("idx_stage", "ALTER TABLE notices ADD INDEX idx_stage (notice_stage)"),
                ("idx_project", "ALTER TABLE notices ADD INDEX idx_project (project_key)"),
            ]:
                if not index_exists(cur, "notices", idx):
                    cur.execute(ddl)
                    print("ADD INDEX", idx)
                else:
                    print("SKIP INDEX", idx)
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
