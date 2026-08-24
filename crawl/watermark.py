"""P7 召回自证：水位游标（每站已见 external_id 集合持久化）。

语义：watermark 记录的是「原始已见」external_id（含被城市/日期过滤丢弃的），
这样下一轮遇到整页已见即可翻页/停扫，避免永远卡在第一页；
同时给出 wm_new（本轮新见数）/ wm_total（水位规模），让「0 新增」可自证。

存储：data/watermark/<source_id>.json（运行时状态，可 gitignore）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WATERMARK_DIR = Path(os.environ.get("SPIDER_WATERMARK_DIR") or (ROOT / "data" / "watermark"))

MAX_IDS_PER_SOURCE = 8000  # 每站水位上限：超出丢最旧（窗口滚动）


def _path(source_id: str) -> Path:
    return WATERMARK_DIR / f"{source_id}.json"


def _load_ordered(source_id: str) -> list[str]:
    p = _path(source_id)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        ids = data.get("ids") or []
        return [str(x) for x in ids if x]
    except (OSError, json.JSONDecodeError):
        return []


def load(source_id: str) -> set[str]:
    """已见集合（成员判断用）。"""
    return set(_load_ordered(source_id))


def merge(source_id: str, external_ids: list[str]) -> tuple[int, int]:
    """合并本轮「原始已见」id（顺序追加，超出上限丢最旧）。返回 (new_count, total_count)。"""
    ids = [str(x) for x in (external_ids or []) if x]
    if not ids:
        ordered = _load_ordered(source_id)
        return 0, len(ordered)
    seen = set(_load_ordered(source_id))
    ordered = _load_ordered(source_id)
    new = 0
    for x in ids:
        if x not in seen:
            seen.add(x)
            ordered.append(x)
            new += 1
    if len(ordered) > MAX_IDS_PER_SOURCE:
        ordered = ordered[-MAX_IDS_PER_SOURCE:]
    WATERMARK_DIR.mkdir(parents=True, exist_ok=True)
    _path(source_id).write_text(
        json.dumps(
            {"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "ids": ordered},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return new, len(ordered)


def size(source_id: str) -> int:
    return len(_load_ordered(source_id))


def reset(source_id: str) -> None:
    p = _path(source_id)
    if p.exists():
        p.unlink()
