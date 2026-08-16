from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect  # noqa: E402

from crawl.config_loader import crawl_cfg, sources_cfg, trial_keywords


def seed_keywords_from_config() -> int:
    cfg = crawl_cfg().get("keywords") or {}
    active = list(cfg.get("active") or cfg.get("core") or [])
    trial = trial_keywords()
    all_kw = []
    for k in active + trial:
        if k not in all_kw:
            all_kw.append(k)
    conn = connect(autocommit=True)
    n = 0
    try:
        with conn.cursor() as cur:
            for kw in all_kw:
                cur.execute(
                    "INSERT INTO keyword_state (keyword, enabled, group_name) VALUES (%s,1,%s) "
                    "ON DUPLICATE KEY UPDATE enabled=1, group_name=VALUES(group_name)",
                    (kw, "active"),
                )
                n += 1
    finally:
        conn.close()
    return n


def set_keyword_enabled(keyword: str, enabled: bool) -> None:
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO keyword_state (keyword, enabled) VALUES (%s,%s) "
                "ON DUPLICATE KEY UPDATE enabled=VALUES(enabled)",
                (keyword, 1 if enabled else 0),
            )
    finally:
        conn.close()


def enabled_keywords(fallback_trial: bool = True) -> list[str]:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT keyword FROM keyword_state WHERE enabled=1 ORDER BY keyword")
            rows = [r["keyword"] for r in cur.fetchall()]
    finally:
        conn.close()
    if rows:
        return rows
    if fallback_trial:
        return trial_keywords()
    return []
