"""Minimal WebBridge client (localhost:10086)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

WB = "http://127.0.0.1:10086/command"


def available(timeout: float = 2.0) -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:10086/command", timeout=timeout)
        return True
    except urllib.error.HTTPError:
        # daemon up but method wrong → still available
        return True
    except Exception:
        return False


def call(action: str, args: dict | None = None, *, session: str = "spiderman", timeout: int = 90) -> dict:
    body = json.dumps({"action": action, "args": args or {}, "session": session}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(WB, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return json.loads(raw)
        except Exception:
            return {"ok": False, "error": {"code": "http_error", "message": raw[:500] or str(e)}}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": {"code": "unreachable", "message": str(e)[:300]}}


def navigate(url: str, *, session: str, group_title: str | None = None, new_tab: bool = True) -> dict:
    args: dict[str, Any] = {"url": url, "newTab": new_tab}
    if group_title:
        args["group_title"] = group_title
    return call("navigate", args, session=session, timeout=45)


def evaluate(code: str, *, session: str) -> dict:
    return call("evaluate", {"code": code}, session=session, timeout=30)


def export_document_cookie(session: str) -> dict:
    """Best-effort cookie string from page JS (non-HttpOnly)."""
    r = evaluate(
        "(() => ({href: location.href, cookie: document.cookie || '', title: document.title}))()",
        session=session,
    )
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error"), "cookie": ""}
    val = (r.get("data") or {}).get("value")
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            pass
    if isinstance(val, dict):
        return {
            "ok": True,
            "cookie": val.get("cookie") or "",
            "href": val.get("href"),
            "title": val.get("title"),
        }
    return {"ok": True, "cookie": str(val or ""), "raw": val}
