"""Lightweight scheduler module (APScheduler optional; stdlib fallback)."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "data" / "web" / "scheduler_state.json"


def _run_incremental():
    cmd = [sys.executable, str(ROOT / "scripts" / "jobs" / "run_incremental.py"), "--pages", "1"]
    p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    return {
        "at": datetime.now().isoformat(timespec="seconds"),
        "returncode": p.returncode,
        "stdout_tail": (p.stdout or "")[-500:],
        "stderr_tail": (p.stderr or "")[-500:],
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
    save_state(st)
    return result


def start_interval_loop(hours: float = 2.0, stop_after: int | None = None):
    """Blocking loop for Windows task alternative. stop_after for tests."""
    n = 0
    interval = max(60.0, hours * 3600)
    while True:
        run_once_and_record()
        n += 1
        if stop_after is not None and n >= stop_after:
            break
        time.sleep(interval)


def start_background_interval(hours: float = 2.0) -> threading.Thread:
    t = threading.Thread(target=start_interval_loop, kwargs={"hours": hours}, daemon=True)
    t.start()
    return t
