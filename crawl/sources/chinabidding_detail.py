"""Optional chinabidding detail enrich via Cookie in .env."""
from __future__ import annotations

import os
import re
import sys
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from db import load_env  # noqa: E402

from crawl.http_session import HttpSession


def cookie_from_env() -> str | None:
    env = load_env()
    c = env.get("CHINABIDDING_COOKIE") or os.environ.get("CHINABIDDING_COOKIE")
    return c.strip() if c else None


def fetch_detail_fields(detail_url: str) -> dict:
    """Return locked/free fields. Without cookie, documents login wall."""
    cookie = cookie_from_env()
    http = HttpSession("chinabidding")
    headers = {"Referer": "https://www.chinabidding.com.cn/"}
    if cookie:
        headers["Cookie"] = cookie
    out: dict = {"login_wall": not bool(cookie), "has_cookie": bool(cookie)}
    try:
        html = http.get_text(detail_url, headers=headers)
    except Exception as e:
        out["error"] = str(e)[:200]
        return out
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", unescape(text))
    login_wall = "立即注册查看" in text or ("请先" in text and "注册" in text)
    out["login_wall"] = bool(login_wall and not cookie)
    for lab, key in [
        (r"招标编号[：:\s]*([^\s立即]{2,40})", "project_code"),
        (r"招标人[：:\s]*([^\s立即]{2,40})", "buyer"),
        (r"招标代理[：:\s]*([^\s立即]{2,40})", "agency"),
        (r"(?:预算|金额)[：:\s]*([0-9,.]+)\s*万?元?", "amount_text"),
    ]:
        m = re.search(lab, text)
        if m and "立即注册" not in m.group(1):
            out[key] = m.group(1).strip()
    return out
