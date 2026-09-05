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


def list_tabs(*, session: str = "spiderman", timeout: int = 30) -> list[dict]:
    """列出当前桥内打开的 tab（含 tabId/groupTitle）。"""
    r = call("list_tabs", {}, session=session, timeout=timeout)
    return list((r.get("data") or {}).get("tabs") or [])


def close_tab(tab_id, *, session: str = "spiderman", timeout: int = 30) -> bool:
    """按 tabId 关闭一个 tab。返回是否关闭成功。"""
    r = call("close_tab", {"tabId": tab_id}, session=session, timeout=timeout)
    return bool((r.get("data") or {}).get("closed"))


def close_group(group_title: str, *, session: str = "spiderman", timeout: int = 30) -> int:
    """关闭指定 group 下的所有 tab，返回关闭数。用完桥后清理，避免浏览器吃内存卡死。"""
    closed = 0
    for t in list_tabs(session=session, timeout=timeout):
        if not isinstance(t, dict):
            continue
        if (t.get("groupTitle") or t.get("group_title")) == group_title:
            if close_tab(t.get("tabId"), session=session, timeout=timeout):
                closed += 1
    return closed



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
        with urllib.request.urlopen("http://127.0.0.1:10086/status", timeout=2) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        ext = 1 if data.get("extension_connected") else 0
        return {"up": bool(data.get("running", True)), "extensions": ext, "raw": data}
    except Exception:
        return {"up": False, "extensions": 0}


def _start_official_daemon() -> bool:
    """启动官方 kimi-webbridge daemon（v2.x 扩展配套，替代旧 Python 桥服务）。返回是否成功监听。"""
    import os
    import subprocess
    from pathlib import Path

    home = Path(os.environ.get("USERPROFILE") or Path.home())
    bin_path = home / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe"
    if not bin_path.exists():
        return False
    try:
        subprocess.run([str(bin_path), "start"], capture_output=True, timeout=30)
    except Exception:
        return False
    for _ in range(20):
        time.sleep(0.5)
        if _bridge_status()["up"]:
            return True
    return False


def _open_browser_if_needed() -> str | None:
    """确保 Chrome 在跑（扩展装在 Chrome，Edge 扩展已弃用）。Chrome 没开就开一个，加 --no-proxy-server 直连。"""
    import subprocess

    if _process_running("chrome.exe"):
        return None
    exe = _first_existing(CHROME_CANDIDATES)
    if not exe:
        return None
    kwargs = {}
    if hasattr(subprocess, "DETACHED_PROCESS"):
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS
    subprocess.Popen([exe, "--no-proxy-server"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs)
    return exe


def ensure_bridge(*, open_browser: bool = True, wait_sec: float = 90.0) -> dict:
    """一键开桥（幂等）：桥没起→起桥服务；浏览器没开→开浏览器；等扩展连上。

    返回 {bridge, extensions, actions}。采集员/爬虫在跑 webbridge 源前调用，
    以后再也不用手工"打开 webbridge"。"""
    actions: list[str] = []
    st = _bridge_status()
    if not st["up"]:
        actions.append("start_daemon")
        if not _start_official_daemon():
            return {"bridge": False, "extensions": 0, "actions": actions, "error": "daemon_start_failed"}
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


def cdp(method: str, params: dict | None = None, *, session: str, timeout: int = 60) -> dict:
    """原始 CDP 透传（扩展白名单：Network.getCookies / Runtime.evaluate 等）。"""
    return call("cdp", {"method": method, "params": params or {}}, session=session, timeout=timeout)


def export_cookies(url: str, *, session: str) -> dict:
    """按 url 取全量 Cookie（含 HttpOnly）via CDP Network.getCookies。

    返回 {ok, cookie(header 串), cookies(list), error}。
    与 export_document_cookie 的区别：document.cookie 拿不到 HttpOnly，这里能拿全。
    """
    urls = [url] if isinstance(url, str) else list(url)
    r = cdp("Network.getCookies", {"urls": urls}, session=session)
    if not r.get("ok"):
        return {"ok": False, "error": r.get("error"), "cookie": "", "cookies": []}
    data = r.get("data") or {}
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = {}
    cookies = (data or {}).get("cookies") or []
    parts = [f"{c['name']}={c['value']}" for c in cookies if c.get("name") is not None]
    return {"ok": True, "cookie": "; ".join(parts), "cookies": cookies}
