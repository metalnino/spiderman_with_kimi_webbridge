"""Persist per-source cookies for HTTP reuse (local only; gitignored)."""
from __future__ import annotations

import json
from datetime import datetime
from http.cookiejar import Cookie
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from crawl.config_loader import ROOT

SESSION_DIR = ROOT / "data" / "sessions"


def path_for(source_id: str) -> Path:
    return SESSION_DIR / f"{source_id}.cookies.json"


def save_cookie_header(
    source_id: str,
    cookie_header: str,
    *,
    meta: dict | None = None,
) -> Path:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_id": source_id,
        "cookie": (cookie_header or "").strip(),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "meta": meta or {},
    }
    p = path_for(source_id)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def load(source_id: str) -> dict | None:
    p = path_for(source_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not (data.get("cookie") or "").strip():
        return None
    return data


def cookie_header(source_id: str) -> str | None:
    data = load(source_id)
    if not data:
        return None
    c = (data.get("cookie") or "").strip()
    return c or None


def apply_to_jar(cj, cookie_header_str: str, url: str) -> int:
    """Parse Cookie header into CookieJar for domain of url. Returns count."""
    host = urlparse(url).hostname or ""
    if not host or not cookie_header_str:
        return 0
    n = 0
    for part in cookie_header_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name, value = name.strip(), value.strip()
        if not name:
            continue
        c = Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain=host,
            domain_specified=True,
            domain_initial_dot=host.startswith("."),
            path="/",
            path_specified=True,
            secure=urlparse(url).scheme == "https",
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
        try:
            cj.set_cookie(c)
            n += 1
        except Exception:
            continue
    return n


def status(source_id: str) -> dict[str, Any]:
    data = load(source_id)
    if not data:
        return {"has_cookie": False, "source_id": source_id}
    return {
        "has_cookie": True,
        "source_id": source_id,
        "saved_at": data.get("saved_at"),
        "cookie_len": len(data.get("cookie") or ""),
        "meta": data.get("meta") or {},
    }
