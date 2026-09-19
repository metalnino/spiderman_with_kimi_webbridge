"""源头追溯员（origin-tracer）台账迁移：notices 增加 origin_* 追溯列。

幂等：已存在的列/索引跳过。与采集员的 detail_status 完全分离（追溯不覆盖采集状态）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect, load_env  # noqa: E402

COLUMNS = [
    ("origin_level", "ALTER TABLE notices ADD COLUMN origin_level VARCHAR(16) NULL "
                     "COMMENT '源头定性: head/gov/platform/aggregator/mirror/unknown'"),
    ("origin_portal", "ALTER TABLE notices ADD COLUMN origin_portal VARCHAR(128) NULL "
                      "COMMENT '源头平台名（源头追溯员）'"),
    ("origin_detail_url", "ALTER TABLE notices ADD COLUMN origin_detail_url VARCHAR(1024) NULL "
                          "COMMENT '源头详情页 URL（一手正文）'"),
    ("origin_status", "ALTER TABLE notices ADD COLUMN origin_status VARCHAR(32) NULL "
                      "COMMENT '追溯状态: ok/partial/not_found/no_hint/portal_down/fetch_failed/no_bridge/error'"),
    ("origin_confidence", "ALTER TABLE notices ADD COLUMN origin_confidence DECIMAL(4,3) NULL "
                          "COMMENT '追溯置信度 0~1'"),
    ("origin_evidence", "ALTER TABLE notices ADD COLUMN origin_evidence JSON NULL "
                        "COMMENT '追溯证据（锚点/候选/方法/说明）'"),
    ("origin_traced_at", "ALTER TABLE notices ADD COLUMN origin_traced_at DATETIME NULL "
                         "COMMENT '最近一次追溯时间'"),
]

INDEXES = [
    ("idx_origin_status", "ALTER TABLE notices ADD INDEX idx_origin_status (origin_status)"),
    ("idx_origin_detail", "ALTER TABLE notices ADD INDEX idx_origin_detail (origin_detail_url(191))"),
]


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


def main() -> int:
    conn = connect(autocommit=True)
    added = 0
    try:
        with conn.cursor() as cur:
            for col, ddl in COLUMNS:
                if column_exists(cur, "notices", col):
                    print("SKIP", col)
                else:
                    cur.execute(ddl)
                    print("ADD", col)
                    added += 1
            for idx, ddl in INDEXES:
                if index_exists(cur, "notices", idx):
                    print("SKIP INDEX", idx)
                else:
                    cur.execute(ddl)
                    print("ADD INDEX", idx)
        print(f"OK 源头追溯台账迁移完成（新增 {added} 列）")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
