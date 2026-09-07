"""采集员详情补全入口 —— 对「已入库但缺详情」的公告补详情/原发/转爬 + AI 字段抽取。

这是采集员「从纯规则到 agent」的纵向补全，**独立于定时任务**（SpidermanCollector 11:00/22:00
仍只做列表采集，不受影响）。手动或另配定时跑：

  对每条缺详情公告（summary 为空且 detail_url 非空）：
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
    stats: dict = {
        "use_ai": use_ai,
        "candidates": 0,
        "processed": 0,
        "detail_ok": 0,
        "detail_failed": 0,
        "ai_ok": 0,
        "ai_failed": 0,
        "per_source": {},
        "errors": [],
        "traces": [],  # 每条公告的决策链留痕（详情/原发/转爬/AI），供自评与调试
    }
    cands = _candidates(limit_total * 3)  # 多取留 per-source 截断余量
    stats["candidates"] = len(cands)
    done = 0
    for c in cands:
        if done >= limit_total:
            break
        sid = c["source_id"]
        per = stats["per_source"].setdefault(sid, {"attempted": 0, "detail_ok": 0, "ai_ok": 0})
        if per["attempted"] >= per_source_limit:
            continue
        per["attempted"] += 1
        done += 1
        trace: dict = {"id": c["id"], "source_id": sid, "title": (c.get("title") or "")[:40]}
        # 1) 规则详情 + 原发寻址 + 原发转爬
        try:
            r = backfill_notice(c["id"])
        except Exception as e:  # noqa: BLE001
            r = {"ok": False, "error": f"{type(e).__name__}:{e}"[:120]}
        trace["detail"] = {
            "ok": bool(r.get("ok")),
            "error": r.get("error"),
            "origin_url": r.get("original_url"),
            "origin_source": r.get("origin_source"),
            "origin_fetched": bool(r.get("origin_fetched")),
        }
        if r.get("ok"):
            stats["detail_ok"] += 1
            per["detail_ok"] += 1
        else:
            stats["detail_failed"] += 1
            stats["errors"].append({"id": c["id"], "source_id": sid, "error": r.get("error")})
        # 2) AI 兜底（summary 为空时 ai_enrich 会如实 no_summary）
        if use_ai:
            try:
                a = ai_enrich_notice(c["id"])
            except Exception as e:  # noqa: BLE001
                a = {"ok": False, "error": f"{type(e).__name__}:{e}"[:120]}
            trace["ai"] = {"ok": bool(a.get("ok")), "filled": a.get("filled"), "error": a.get("error")}
            if a.get("ok"):
                stats["ai_ok"] += 1
                per["ai_ok"] += 1
            else:
                stats["ai_failed"] += 1
        stats["traces"].append(trace)
    stats["processed"] = done
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
