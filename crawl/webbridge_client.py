"""Minimal WebBridge client (localhost:10086)."""
from __future__ import annotations

import json
import time
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




# ---------------------------------------------------------------- 开桥（幂等自愈） ---

CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Users\27915\AppData\Local\Google\Chrome\Application\chrome.exe",
)
EDGE_CANDIDATES = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def _first_existing(paths) -> str | None:
    import os
    for p in paths:
        if os.path.isfile(p):
            return p
    return None


def _process_running(image: str) -> bool:
    import subprocess
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=10,
        )
        return image.lower() in (r.stdout or "").lower()
    except Exception:
        return False


def _bridge_status() -> dict:
    try:
        with urllib.request.urlopen("http://127.0.0.1:10086/", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {"up": True, "extensions": int(data.get("extensions_connected") or 0), "raw": data}
    except Exception:
        return {"up": False, "extensions": 0}


def _spawn_server() -> bool:
    """后台启动桥服务端（与调用方进程脱离，调用方退出后桥仍在）。返回是否成功监听。"""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    server = root / "scripts" / "webbridge_server.py"
    logf = root / "data" / "web" / "webbridge_server.log"
    logf.parent.mkdir(parents=True, exist_ok=True)
    pidfile = root / "data" / "web" / "webbridge_server.pid"
    kwargs = {}
    if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    with open(logf, "a", encoding="utf-8") as out:
        subprocess.Popen(
            [sys.executable, str(server)],
            cwd=str(root),
            stdout=out,
            stderr=out,
            stdin=subprocess.DEVNULL,
            env={**__import__("os").environ, "WEBRIDGE_PIDFILE": str(pidfile)},
            **kwargs,
        )
    for _ in range(20):
        time.sleep(0.5)
        if _bridge_status()["up"]:
            return True
    return False


def _open_browser_if_needed() -> str | None:
    """浏览器没开就开一个（Chrome 优先，扩展会自动连桥）。返回启动的程序路径或 None。"""
    import subprocess

    if _process_running("chrome.exe") or _process_running("msedge.exe"):
        return None
    exe = _first_existing(CHROME_CANDIDATES) or _first_existing(EDGE_CANDIDATES)
    if not exe:
        return None
    kwargs = {}
    if hasattr(subprocess, "DETACHED_PROCESS"):
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS
    subprocess.Popen([exe], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    return exe


def ensure_bridge(*, open_browser: bool = True, wait_sec: float = 90.0) -> dict:
    """一键开桥（幂等）：桥没起→起桥服务；浏览器没开→开浏览器；等扩展连上。

    返回 {bridge, extensions, actions}。采集员/爬虫在跑 webbridge 源前调用，
    以后再也不用手工"打开 webbridge"。"""
    actions: list[str] = []
    st = _bridge_status()
    if not st["up"]:
        actions.append("spawn_server")
        if not _spawn_server():
            return {"bridge": False, "extensions": 0, "actions": actions, "error": "server_start_failed"}
        st = _bridge_status()
    if st["extensions"] < 1 and open_browser:
        opened = _open_browser_if_needed()
        if opened:
            actions.append(f"opened_browser:{opened}")
        deadline = time.time() + wait_sec
        while time.time() < deadline and _bridge_status()["extensions"] < 1:
            time.sleep(3)
    st = _bridge_status()
    return {"bridge": st["up"], "extensions": st["extensions"], "actions": actions}



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
