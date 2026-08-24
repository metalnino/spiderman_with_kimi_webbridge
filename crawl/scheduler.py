"""Lightweight scheduler: fixed daily slots in Asia/Shanghai (stdlib only)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo

    TZ = ZoneInfo("Asia/Shanghai")
except Exception:  # noqa: BLE001 — Windows 无 tzdata 时回退固定东八区
    TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data" / "web" / "scheduler_state.json"
DEFAULT_SLOTS = ((8, 0), (12, 0), (18, 0), (22, 0))


def _now() -> datetime:
    return datetime.now(TZ)


def parse_slots(raw: str | None) -> list[tuple[int, int]]:
    """Parse '8,12,18,22' or '8:00,12:00' → [(h,m), ...]；'off'/'none'/'disabled' → []（关闭调度）。"""
    if not raw or not str(raw).strip():
        return list(DEFAULT_SLOTS)
    if str(raw).strip().lower() in ("off", "none", "disabled"):
        return []
    out: list[tuple[int, int]] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            h_s, m_s = part.split(":", 1)
            out.append((int(h_s), int(m_s)))
        else:
            out.append((int(part), 0))
    return out or list(DEFAULT_SLOTS)


def next_slot_after(now: datetime | None = None, slots: list[tuple[int, int]] | None = None) -> datetime:
    """Next wall-clock run strictly after `now` in Asia/Shanghai."""
    now = now.astimezone(TZ) if now else _now()
    slots = sorted(slots or list(DEFAULT_SLOTS))
    for h, m in slots:
        cand = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if cand > now:
            return cand
    h0, m0 = slots[0]
    tomorrow = (now + timedelta(days=1)).replace(hour=h0, minute=m0, second=0, microsecond=0)
    return tomorrow


def _run_incremental():
    pages = os.environ.get("CRAWL_PAGES", "1")
    # CRAWL_MODE=collector：调度槽跑员工壳（六站全开，含 playwright/webbridge 路由），
    # 产出契约 output + 观测报告；否则维持原 HTTP 增量入口。
    if os.environ.get("CRAWL_MODE") == "collector":
        cmd = [sys.executable, str(ROOT / "scripts" / "collector_run.py")]
    else:
        cmd = [sys.executable, str(ROOT / "scripts" / "jobs" / "run_incremental.py"), "--pages", str(pages)]
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    # 每轮增量后重建 CRM（失败不挡主流程）
    crm = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "jobs" / "build_crm_db.py")],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    return {
        "at": _now().isoformat(timespec="seconds"),
        "returncode": p.returncode,
        "stdout_tail": (p.stdout or "")[-500:],
        "stderr_tail": (p.stderr or "")[-500:],
        "crm_returncode": crm.returncode,
        "crm_stdout_tail": (crm.stdout or "")[-200:],
    }


def save_state(obj: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state() -> dict:
    if not STATE.exists():
        return {"runs": []}
    return json.loads(STATE.read_text(encoding="utf-8"))


def run_once_and_record() -> dict:
    result = _run_incremental()
    st = load_state()
    runs = st.get("runs") or []
    runs.insert(0, result)
    st["runs"] = runs[:30]
    st["last"] = result
    st["tz"] = "Asia/Shanghai"
    st["slots"] = [f"{h:02d}:{m:02d}" for h, m in parse_slots(os.environ.get("CRAWL_CRON_HOURS"))]
    save_state(st)
    return result


def start_cron_loop(
    slots: list[tuple[int, int]] | None = None,
    *,
    stop_after: int | None = None,
    run_immediately: bool = False,
):
    """Blocking loop: sleep until next Shanghai slot, then crawl. For tests use stop_after."""
    slots = slots or parse_slots(os.environ.get("CRAWL_CRON_HOURS"))
    n = 0
    if run_immediately:
        run_once_and_record()
        n += 1
        if stop_after is not None and n >= stop_after:
            return
    while True:
        now = _now()
        nxt = next_slot_after(now, slots)
        wait = max(1.0, (nxt - now).total_seconds())
        print(f"[scheduler] tz=Asia/Shanghai next={nxt.isoformat(timespec='seconds')} wait_s={int(wait)}", flush=True)
        # 分段睡，便于信号/测试打断观感
        end = time.time() + wait
        while time.time() < end:
            time.sleep(min(60.0, end - time.time()))
        run_once_and_record()
        n += 1
        if stop_after is not None and n >= stop_after:
            break


def start_interval_loop(hours: float = 2.0, stop_after: int | None = None):
    """兼容旧入口：忽略 hours，改走固定时刻表。"""
    start_cron_loop(stop_after=stop_after, run_immediately=False)


def start_background_interval(hours: float = 2.0) -> threading.Thread:
    t = threading.Thread(target=start_cron_loop, kwargs={"run_immediately": False}, daemon=True)
    t.start()
    return t
