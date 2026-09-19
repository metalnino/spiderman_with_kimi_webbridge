"""采集员详情补全入口 —— 对「已入库但缺详情」的公告补详情/原发/转爬 + AI 字段抽取。

**编排实现在 crawl/detail_pass.py，与采集轮共用同一份**（2026-09-19 起）：
  - 定时链路：SpidermanCollector（11:00/22:00）在列表采集后会跑一个有界的详情正文补全阶段
    （默认单轮 ≤80 条、每站 ≤10 条、限时 900s；配置见 config/anti_bot.json 的 `detail_pass`，
    报告字段 `detailPass`）。此前这条链**没有任何定时入口**，导致 3166 条里 3103 条
    detail_status 为 null、只有 7 条落了附件正文 —— 下游解析员直接断粮。
  - 本脚本 = **手动/大批量**入口：不限时、不做优先级重排（候选沿用 `summary IS NULL` 口径）。

对每条候选公告：
    1) backfill_notice：详情抓取 → 原发寻址 → 原发转爬（规则，复用 P4/P5 能力）
    2) ai_enrich_notice：AI 对 summary 抽取规则缺失的字段兜底（可关）

用法:
  python scripts/collector_detail.py                  # 默认 20 条 / 每站 5 / 开 AI
  python scripts/collector_detail.py --limit 50 --per-source 10
  python scripts/collector_detail.py --no-ai          # 只做规则详情补全
  SPIDER_NO_AI=1 python scripts/collector_detail.py   # 同 --no-ai

护栏：单轮总数 + 每源站数封顶；AI 只补规则缺失字段、绝不覆盖；抽不到如实空。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from db import connect  # noqa: E402
from crawl.backfill import ai_enrich_notice, backfill_notice  # noqa: E402


def _candidates(limit: int) -> list[dict]:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, source_id, title, detail_url FROM notices "
                "WHERE summary IS NULL AND detail_url IS NOT NULL "
                "ORDER BY id DESC LIMIT %s",
                (limit,),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def run(*, limit_total: int = 20, per_source_limit: int = 5, use_ai: bool = True) -> dict:
    """手动入口编排 —— 真正的实现在 crawl/detail_pass.py（与采集轮共用同一份）。

    手动跑：不限时（max_seconds=0）、候选沿用旧口径（`_candidates` 自己挑，不做优先级重排），
    便于运维按需大批量补。定时链路（采集轮内）用的是优先级候选 + 三重封顶。
    """
    from crawl.detail_pass import run_detail_pass

    stats = run_detail_pass(
        limit_total=limit_total,
        per_source_limit=per_source_limit,
        max_seconds=0,
        min_summary_chars=0,
        use_ai=use_ai,
        retry_error_prefixes=(),
        candidates_fn=lambda: _candidates(limit_total * 3),
        backfill_fn=backfill_notice,  # 保留模块级引用：单测可注入
        ai_fn=ai_enrich_notice,
        log=lambda msg: print(msg, flush=True),
    )
    stats["detail_failed"] = stats["failed"]  # 兼容旧键名
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description="采集员详情补全（详情→原发→转爬 + AI 兜底）")
    ap.add_argument("--limit", type=int, default=20, help="单轮总数上限（默认 20）")
    ap.add_argument("--per-source", type=int, default=5, help="每源站数上限（默认 5）")
    ap.add_argument("--no-ai", action="store_true", help="关闭 AI 兜底")
    args = ap.parse_args()

    use_ai = (not args.no_ai) and ("SPIDER_NO_AI" not in os.environ)
    stats = run(limit_total=args.limit, per_source_limit=args.per_source, use_ai=use_ai)
    print(json.dumps({"ok": True, **stats}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
