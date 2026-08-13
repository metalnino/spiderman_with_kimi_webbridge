"""MySQL helper for this workspace. Credentials from project .env only."""
from __future__ import annotations

import os
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor

ROOT = Path(__file__).resolve().parents[1]


def load_env(path: Path | None = None) -> dict[str, str]:
    """Load MYSQL_* from .env file; if missing, fall back to process env (Docker env_file)."""
    env_path = path or (ROOT / ".env")
    out: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    # Docker compose env_file / environment 注入时没有 /app/.env 文件
    keys = (
        "MYSQL_HOST",
        "MYSQL_PORT",
        "MYSQL_USER",
        "MYSQL_PASSWORD",
        "MYSQL_DATABASE",
        "MYSQL_CHARSET",
        "CHINABIDDING_COOKIE",
    )
    for k in keys:
        if k not in out and os.environ.get(k):
            out[k] = os.environ[k].strip()
    required = ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE")
    missing = [k for k in required if not out.get(k)]
    if missing:
        raise FileNotFoundError(
            f"missing DB config {missing}; provide .env or env vars (copy .env.example to .env)"
        )
    return out


def connect(database: str | None = "", *, autocommit: bool = True, use_env_db: bool = True):
    """Connect. use_env_db=True 默认连 .env 里的库；建库阶段传 use_env_db=False。"""
    cfg = load_env()
    kwargs = {
        "host": cfg["MYSQL_HOST"],
        "port": int(cfg.get("MYSQL_PORT") or 3306),
        "user": cfg["MYSQL_USER"],
        "password": cfg["MYSQL_PASSWORD"],
        "charset": cfg.get("MYSQL_CHARSET") or "utf8mb4",
        "cursorclass": DictCursor,
        "autocommit": autocommit,
    }
    db = cfg.get("MYSQL_DATABASE") if use_env_db else database
    if database and use_env_db:
        db = database
    if not use_env_db:
        db = database or None
    if db:
        kwargs["database"] = db
    return pymysql.connect(**kwargs)


def ping() -> dict:
    cfg = load_env()
    conn = connect(use_env_db=False)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION() AS v, @@character_set_server AS charset")
            row = cur.fetchone()
            cur.execute("SHOW DATABASES LIKE %s", (cfg["MYSQL_DATABASE"],))
            exists = cur.fetchone() is not None
        return {
            "ok": True,
            "host": cfg["MYSQL_HOST"],
            "port": int(cfg.get("MYSQL_PORT") or 3306),
            "database": cfg["MYSQL_DATABASE"],
            "version": row["v"],
            "server_charset": row["charset"],
            "db_exists": exists,
        }
    finally:
        conn.close()
