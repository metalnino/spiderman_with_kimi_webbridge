"""Workbench write actions: lead updates, crawl trigger. Read-only queries stay in ledger_data."""
from __future__ import annotations

import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect  # noqa: E402

LEAD_STATUSES = ("待处理", "跟进中", "已成交", "已放弃", "忽略")
AMOUNT_STATUSES = ("待确认", "已确认", "无金额")


def update_notice_lead(
    notice_id: int,
    *,
    read: bool = False,
    lead_status: str | None = None,
    amount_status: str | None = None,
    remark: str | None = None,
) -> dict:
    sets: list[str] = []
    params: list = []
    if read:
        sets.append("read_at=%s")
        params.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if lead_status is not None:
        if lead_status not in LEAD_STATUSES:
            return {"ok": False, "error": "bad_lead_status"}
        sets.append("lead_status=%s")
        params.append(lead_status)
    if amount_status is not None:
        if amount_status not in AMOUNT_STATUSES:
            return {"ok": False, "error": "bad_amount_status"}
        sets.append("amount_status=%s")
        params.append(amount_status)
    if remark is not None:
        sets.append("remark=%s")
        params.append((remark or "")[:500])
    if not sets:
        return {"ok": False, "error": "no_fields"}
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM notices WHERE id=%s", (notice_id,))
            if cur.fetchone() is None:
                return {"ok": False, "error": "not_found", "notice_id": notice_id}
            params.append(notice_id)
            cur.execute(f"UPDATE notices SET {', '.join(sets)} WHERE id=%s", tuple(params))
        return {"ok": True, "notice_id": notice_id}
    finally:
        conn.close()


_lock = threading.Lock()
_running = False


def _crawl_is_running() -> bool:
    return _running


def trigger_crawl(pages: int = 1, sources: list[str] | None = None) -> dict:
    """触发一轮增量（后台子进程）。"""
    global _running
    with _lock:
        if _running:
            return {"ok": False, "error": "already_running"}
        cmd = [sys.executable, str(ROOT / "scripts" / "jobs" / "run_incremental.py"), "--pages", str(pages)]
        if sources:
            cmd += ["--sources", ",".join(sources)]
        try:
            p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:200]}
        _running = True

    def _waiter():
        global _running
        p.wait()
        with _lock:
            _running = False

    threading.Thread(target=_waiter, daemon=True).start()
    return {"ok": True, "triggered": True, "pid": p.pid, "pages": pages}
