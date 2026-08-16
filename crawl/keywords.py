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


def all_keywords() -> list[dict]:
    """词库全量（含启停状态）。"""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT keyword, enabled, group_name FROM keyword_state ORDER BY enabled DESC, keyword")
            return list(cur.fetchall())
    finally:
        conn.close()


def add_keyword(keyword: str, group_name: str = "active", enabled: bool = True) -> dict:
    kw = (keyword or "").strip()
    if not kw:
        return {"ok": False, "error": "empty_keyword"}
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO keyword_state (keyword, enabled, group_name) VALUES (%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE enabled=VALUES(enabled), group_name=VALUES(group_name)",
                (kw, 1 if enabled else 0, group_name),
            )
    finally:
        conn.close()
    sync_config_keywords()
    return {"ok": True, "keyword": kw}


def delete_keyword(keyword: str) -> dict:
    kw = (keyword or "").strip()
    if not kw:
        return {"ok": False, "error": "empty_keyword"}
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM keyword_state WHERE keyword=%s", (kw,))
    finally:
        conn.close()
    sync_config_keywords()
    return {"ok": True, "keyword": kw}


def sync_config_keywords() -> dict:
    """把当前启用关键词回写到 config/crawl_config.json 的 keywords.active（作模板）。"""
    import json

    from crawl.config_loader import ROOT

    kws = enabled_keywords(fallback_trial=False)
    if not kws:
        return {"ok": False, "error": "no_enabled_keywords"}
    path = ROOT / "config" / "crawl_config.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("keywords", {})["active"] = kws
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "active": kws}
