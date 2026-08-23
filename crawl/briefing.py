"""P5 出勤简报：读取 reports/briefing.jsonl，计算趋势（连续零产出/失败）。

简报 JSONL 由采集员每次运行追加一行（见 crawl.collector_employee.run），
本模块提供只读分析与展示，供台账「员工考勤」或脚本查看。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIEFING_PATH = ROOT / "reports" / "briefing.jsonl"


def load(path: Path | None = None, limit: int = 200) -> list[dict]:
    """读最近 limit 行简报（时间正序，新在后）。损坏行跳过。"""
    p = path or BRIEFING_PATH
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out[-limit:]


def last(path: Path | None = None) -> dict | None:
    rows = load(path, limit=1)
    return rows[-1] if rows else None


def consecutive_empty(briefs: list[dict], platforms: list[str]) -> dict[str, int]:
    """每个平台从最近一轮往前连续「零产出」的轮数（未出勤同样计入空窗）。

    fetched>0 即断档并锁定（更早的空窗不再计）。返回 {platform: 连续空窗轮数}。
    """
    counts = {p: 0 for p in platforms}
    locked: set[str] = set()
    for b in reversed(briefs):
        ran = set(b.get("platforms") or [])
        for p in platforms:
            if p in locked:
                continue
            if p not in ran:
                counts[p] += 1  # 未出勤，视为空窗延续
                continue
            if b.get("fetched") == 0 or p in (b.get("empty_platforms") or []):
                counts[p] += 1
            else:
                locked.add(p)  # 该轮有产出，空窗到此为止
    return counts


def summary(path: Path | None = None, platforms: list[str] | None = None) -> dict:
    """考勤摘要：最近一轮 + 各站连续空窗 + 待办。"""
    briefs = load(path)
    if not briefs:
        return {"runs": 0, "last": None, "consecutive_empty": {}, "open_todos": None, "window_note": None}
    plats = platforms or sorted({p for b in briefs for p in (b.get("platforms") or [])})
    last_b = briefs[-1]
    return {
        "runs": len(briefs),
        "last": last_b,
        "consecutive_empty": consecutive_empty(briefs, plats),
        "open_todos": last_b.get("open_todos"),
        "window_note": last_b.get("window_note"),
    }
