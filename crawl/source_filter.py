"""浏览器源（WebBridge / Playwright）的入库过滤口径 —— 与 HTTP 内核 runner.run_source 完全一致。

为什么需要抽出来：HTTP 源由 `crawl/runner.py` 统一做「8 城白名单 + 发布时间窗」过滤，
但**浏览器源是各自模块直接 upsert 的**，过滤要靠模块自己实现。实测（2026-09-19）后果：
  - jiangsu_zhaobiao / qianlima / cebpub：0 条越界（各自实现了过滤或站点侧已是窗口内）；
  - **tgnet：385 条里有 340 条早于窗口起点、319 条不在 8 城**（跨 2008–2026 的工程库），
    每轮还把 373 条重新 upsert 一遍 —— 白刷且污染台账。
口径铁律与内核一致：
  1) 只在 only_target_cities() 打开时按 8 城过滤（城市为空按不匹配处理，与内核 same）；
  2) 发布时间：区间外丢弃，**无日期不丢**（与内核一致，避免因解析缺失误杀）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crawl.config_loader import (  # noqa: E402
    only_target_cities,
    publish_date_range,
    target_city_names,
)


def filter_notices(notices: list) -> tuple[list, int]:
    """按内核口径过滤 city/publish_date，返回 (kept, dropped)。"""
    total = len(notices)
    if only_target_cities():
        targets = set(target_city_names())
        notices = [n for n in notices if (getattr(n, "city", "") or "") in targets]
    pmin, pmax = publish_date_range()
    if pmin or pmax:
        kept = []
        for n in notices:
            pub = (getattr(n, "publish_date", "") or "")[:10]
            if not pub:
                kept.append(n)  # 无日期不因范围丢弃（与内核一致）
            elif (not pmin or pub >= pmin) and (not pmax or pub <= pmax):
                kept.append(n)
        notices = kept
    return notices, total - len(notices)
