"""P7 ccgp 回溯扫描：按日切片扫发布时间窗口（默认 2026-07-01~08-31），补历史召回缺口。

背景：ccgp 列表默认只扫第一页且 timeType=5 无时间段参数时窗口漂移，
「8城×7-8月交集极少」实为扫描策略缺陷（实测连续多轮 raw=20 完全重复）。
本作业把窗口切成 62 天逐日请求（timeType=5 + start_time/end_time=YYYY:MM:DD），
每片翻页直到空/水位边界；结果与 runner 同口径过滤（目标城市+日期）后入库。

用法：
  python scripts/jobs/backfill_ccgp_window.py [--start 2026-07-01] [--end 2026-08-31] [--max-pages 30]
断点续扫：状态存 data/watermark/ccgp_backfill_state.json；失败日如实记录并停止（下次从断点继续）。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from crawl.config_loader import only_target_cities, publish_date_range, target_city_names  # noqa: E402
from crawl.db_store import upsert_notices  # noqa: E402
from crawl.sources.ccgp import CcgpSource  # noqa: E402
from crawl import watermark  # noqa: E402

STATE_PATH = watermark.WATERMARK_DIR / "ccgp_backfill_state.json"


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _fmt_day(d: datetime) -> str:
    return d.strftime("%Y:%m:%d")


def main() -> int:
    ap = argparse.ArgumentParser(description="ccgp 逐日回溯扫描")
    ap.add_argument("--start", default="2026-07-01")
    ap.add_argument("--end", default="2026-08-31")
    ap.add_argument("--max-pages", type=int, default=30)
    ap.add_argument("--kw", default="绿植租摆")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")
    state = _load_state()
    day = datetime.strptime(state.get("next_day", args.start), "%Y-%m-%d") \
        if state.get("next_day") else start

    src = CcgpSource()
    targets = set(target_city_names()) if only_target_cities() else None
    pmin, pmax = publish_date_range()
    total_raw = total_kept = 0
    while day <= end:
        d = _fmt_day(day)
        print(f"[backfill] day={d} ...", flush=True)
        try:
            notices = list(src.fetch([args.kw], max_pages=args.max_pages,
                                     start_time=d, end_time=d))
        except Exception as e:  # noqa: BLE001 —— 频控/网络：如实停，状态不推进，下次续扫
            print(f"[backfill] day={d} FAILED: {e}", flush=True)
            _save_state({"next_day": day.strftime("%Y-%m-%d"), "last_error": str(e)[:200]})
            return 1
        total_raw += len(notices)
        if targets:
            notices = [n for n in notices if (n.city or "") in targets]
        if pmin or pmax:
            notices = [n for n in notices
                       if (not n.publish_date
                           or (not pmin or str(n.publish_date)[:10] >= pmin)
                           and (not pmax or str(n.publish_date)[:10] <= pmax))]
        if notices:
            stats = upsert_notices(notices)
            total_kept += len(notices)
            print(f"[backfill] day={d} kept={len(notices)} (upsert≈{stats['affected']})", flush=True)
        day += timedelta(days=1)
        _save_state({"next_day": day.strftime("%Y-%m-%d"), "last_error": None})
    _save_state({"next_day": day.strftime("%Y-%m-%d"), "done": True, "last_error": None})
    print(f"[backfill] DONE raw={total_raw} kept={total_kept}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
