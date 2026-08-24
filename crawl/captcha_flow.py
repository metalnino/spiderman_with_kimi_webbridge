"""Local human captcha solve: open via WebBridge → colleague slides → save cookies."""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect  # noqa: E402

from crawl import cookie_store, webbridge_client
from crawl.captcha_queue import close_todo
from crawl.warm_session import WARM_URLS


def get_todo(todo_id: int) -> dict | None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, source_id, detail_url, title, status, note, created_at "
                "FROM captcha_todos WHERE id=%s",
                (todo_id,),
            )
            return cur.fetchone()
    finally:
        conn.close()


def _target_url(todo: dict) -> str:
    url = (todo.get("detail_url") or "").strip()
    if url.startswith("http://") or url.startswith("https://"):
        return url
    sid = todo.get("source_id") or ""
    return WARM_URLS.get(sid) or url or "about:blank"


def open_for_human(todo_id: int) -> dict:
    """PO out: open captcha page in WebBridge (fallback system browser)."""
    todo = get_todo(todo_id)
    if not todo:
        return {"ok": False, "error": "todo_not_found", "todo_id": todo_id}
    if todo.get("status") != "open":
        return {"ok": False, "error": "todo_not_open", "status": todo.get("status"), "todo_id": todo_id}
    url = _target_url(todo)
    session = f"captcha-{todo_id}"
    out: dict = {
        "ok": True,
        "todo_id": todo_id,
        "source_id": todo.get("source_id"),
        "url": url,
        "session": session,
        "instruction": "在弹出的浏览器里完成验证码/滑块，完成后点「已解决」或运行 solve_captcha.py done",
    }
    wb_ok = webbridge_client.available()
    out["webbridge"] = wb_ok
    if wb_ok:
        nav = webbridge_client.navigate(url, session=session, group_title=f"captcha-{todo_id}")
        out["nav"] = {"ok": bool(nav.get("ok")), "raw": nav.get("error") or nav.get("data")}
        # navigate timeout 仍可能已开页；再兜底系统浏览器
        if not nav.get("ok"):
            try:
                webbrowser.open(url)
                out["fallback_browser"] = True
            except Exception as e:  # noqa: BLE001
                out["fallback_browser_error"] = str(e)[:200]
    else:
        try:
            webbrowser.open(url)
            out["fallback_browser"] = True
            out["note"] = "WebBridge 未启动，已用系统浏览器打开"
        except Exception as e:  # noqa: BLE001
            out["ok"] = False
            out["error"] = f"open_failed:{e}"
    return out


def resolve_todo(todo_id: int, *, cookie_header: str | None = None, note: str | None = None) -> dict:
    """After human solve: export/save cookies and close todo."""
    todo = get_todo(todo_id)
    if not todo:
        return {"ok": False, "error": "todo_not_found", "todo_id": todo_id}
    source_id = todo.get("source_id") or "unknown"
    session = f"captcha-{todo_id}"
    cookie = (cookie_header or "").strip()
    export: dict = {"ok": False}
    if not cookie:
        # ① CDP 全量（含 HttpOnly）优先；url 用页面真实 href + 待办目标兜底
        try:
            urls = [w for w in (_target_url(todo),) if w.startswith("http")]
            doc = webbridge_client.export_document_cookie(session)
            if doc.get("ok") and (doc.get("href") or "").startswith("http"):
                urls.insert(0, doc["href"])
            export = webbridge_client.export_cookies(urls, session=session)
            if export.get("ok") and export.get("cookie"):
                cookie = export["cookie"]
            else:
                export = {"ok": False, "error": export.get("error"), "cookie": ""}
        except Exception as e:  # noqa: BLE001 —— CDP 不可用时退回 document.cookie
            export = {"ok": False, "error": str(e)[:200], "cookie": ""}
    if not cookie:
        # ② document.cookie（非 HttpOnly）兜底
        export = webbridge_client.export_document_cookie(session)
        if export.get("ok") and export.get("cookie"):
            cookie = export["cookie"]
    if not cookie:
        # ③ 同源暖会话名兜底
        export2 = webbridge_client.export_document_cookie(f"warm-{source_id}")
        if export2.get("ok") and export2.get("cookie"):
            cookie = export2["cookie"]
            export = export2
    saved_path = None
    if cookie:
        saved_path = str(
            cookie_store.save_cookie_header(
                source_id,
                cookie,
                meta={"todo_id": todo_id, "url": _target_url(todo), "export": export},
            )
        )
    closed = close_todo(
        todo_id,
        note=note or ("cookie_saved" if cookie else "closed_without_cookie"),
    )
    return {
        "ok": bool(closed),
        "todo_id": todo_id,
        "source_id": source_id,
        "cookie_saved": bool(cookie),
        "cookie_len": len(cookie) if cookie else 0,
        "path": saved_path,
        "export_ok": bool(export.get("ok")),
        "warning": None if cookie else "未拿到 Cookie（CDP 全量导出与 document.cookie 均失败）；待办已关，可下次重开或手动粘贴 Cookie",
    }


def list_open_detailed(limit: int = 50) -> list[dict]:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, source_id, detail_url, title, status, note, created_at "
                "FROM captcha_todos WHERE status='open' ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            rows = list(cur.fetchall())
    finally:
        conn.close()
    for r in rows:
        sid = r.get("source_id") or ""
        st = cookie_store.status(sid)
        r["has_saved_cookie"] = st.get("has_cookie")
        r["cookie_saved_at"] = st.get("saved_at")
    return rows
