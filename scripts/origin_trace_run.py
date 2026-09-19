"""源头追溯员 CLI 入口（scripts/origin_trace_run.py）。

用法：
  python scripts/origin_trace_run.py --list                     # 看待追溯的项目组
  python scripts/origin_trace_run.py --notice 50343 --apply     # 追单条（含落库）
  python scripts/origin_trace_run.py --limit 3 --apply          # 批量（默认绿植族关键词）
  python scripts/origin_trace_run.py --limit 5 --keywords "绿植租摆|植物租赁" --minutes 15
  python scripts/origin_trace_run.py --project-key <sha1> --no-ai --no-download

产物：
  reports/origin-trace-report.json       本轮报告（含每条 traces）
  handoffs/tracer/latest.json            管道交接物（下游/人可直接读）
  handoffs/tracer/tracer-v1.0.0.json     版本化交接物
挂起/失败一律如实记录，绝不编造源头。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from crawl import origin_trace  # noqa: E402

HANDOFF_DIR = ROOT / "handoffs" / "tracer"
REPORT_PATH = ROOT / "reports" / "origin-trace-report.json"
DEFAULT_KEYWORDS = "绿植租摆|绿植租赁|植物租摆|植物租赁"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def cmd_list(limit: int, keywords: str | None) -> int:
    groups = origin_trace.pick_groups(limit=limit, only_keywords=keywords)
    print(f"待追溯项目组 {len(groups)} 个：")
    for g in groups:
        print(f"  {g['project_key']}  n={g['n']:<3} {g.get('srcs') or ''}  {g.get('last_date')}")
    return 0


def write_handoff(stats: dict, *, apply: bool) -> Path:
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "employee": "tracer",
        "implements": "tracer/v1.0.0",
        "generatedAt": _now(),
        "summary": {
            "candidates": stats.get("candidates"),
            "processed": stats.get("processed"),
            "ok": stats.get("ok"),
            "partial": stats.get("partial"),
            "notFound": stats.get("not_found"),
            "blocked": stats.get("blocked"),
            "applied": stats.get("applied"),
            "stoppedReason": stats.get("stoppedReason"),
            "elapsedMs": stats.get("elapsedMs"),
            "writeBack": bool(apply),
        },
        "origins": [
            {
                "projectKey": r.get("projectKey"),
                "projectName": r.get("projectName"),
                "noticeIds": r.get("noticeIds"),
                "status": r.get("status"),
                "sourceIsOrigin": r.get("sourceIsOrigin"),
                "originLevel": r.get("originLevel"),
                "portalName": r.get("portalName"),
                "portalHome": r.get("portalHome"),
                "detailUrl": r.get("detailUrl"),
                "announcementNo": (r.get("hints") or {}).get("projectCode"),
                "matchScore": r.get("matchScore"),
                "confidence": r.get("confidence"),
                "method": r.get("method"),
                "bodyChars": (r.get("body") or {}).get("chars"),
                "attachments": r.get("attachments"),
                "error": r.get("error"),
            }
            for r in stats.get("records") or []
        ],
    }
    latest = HANDOFF_DIR / "latest.json"
    versioned = HANDOFF_DIR / "tracer-v1.0.0.json"
    for p in (latest, versioned):
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return latest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="源头追溯员：把聚合站公告追到发布主体的源头平台")
    ap.add_argument("--list", action="store_true", help="只列出待追溯项目组")
    ap.add_argument("--notice", type=int, default=None, help="按 notices.id 追单条")
    ap.add_argument("--project-key", default=None, help="按 project_key 追一个项目组")
    ap.add_argument("--origin-url", default=None,
                    help="人工已确认的源头链接（给了就跳过自动发现，直接取回+校验+落库）")
    ap.add_argument("--limit", type=int, default=3, help="批量追溯条数上限（默认 3）")
    ap.add_argument("--keywords", default=DEFAULT_KEYWORDS, help="批量时的标题关键词（RLIKE，空串=不限）")
    ap.add_argument("--minutes", type=int, default=20, help="墙钟预算（分钟）")
    ap.add_argument("--apply", action="store_true", help="结果写回 MySQL（origin_* 列）")
    ap.add_argument("--no-ai", action="store_true", help="关闭 AI 语义抽取（纯规则锚点）")
    ap.add_argument("--no-download", action="store_true", help="不下载源头附件（只要正文）")
    ap.add_argument("--json", action="store_true", help="stdout 打完整 JSON")
    args = ap.parse_args(argv)

    kw = args.keywords or None
    if args.list:
        return cmd_list(max(args.limit, 1), kw)

    if args.notice or args.project_key or args.origin_url:
        rec = origin_trace.trace_one(
            notice_id=args.notice, project_key=args.project_key, origin_url=args.origin_url,
            use_ai=not args.no_ai, download=not args.no_download,
        )
        pub = origin_trace.public_record(rec)
        applied = {}
        if args.apply:
            # 所有终态都落库：not_found / no_hint / portal_down 同样是结论
            # （避免下轮重复劳动，并形成人工接手清单）；apply_record 内部只在 ok/partial 时才覆写正文。
            applied = origin_trace.apply_record(rec)
        stats = {"candidates": 1, "processed": 1, "ok": int(rec.get("status") == "ok"),
                 "partial": int(rec.get("status") == "partial"),
                 "not_found": int(rec.get("status") not in ("ok", "partial")),
                 "blocked": 0, "applied": int(bool(applied)), "stoppedReason": "single",
                 "elapsedMs": rec.get("elapsedMs"), "records": [pub]}
    else:
        stats = origin_trace.trace_batch(
            limit=max(args.limit, 1), keywords=kw, minutes=max(args.minutes, 1),
            use_ai=not args.no_ai, download=not args.no_download, apply=args.apply,
        )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    handoff = write_handoff(stats, apply=args.apply)
    origin_trace_ok = stats.get("ok", 0)

    if args.json:
        print(json.dumps(stats, ensure_ascii=False, indent=2))
    else:
        print(f"追溯完成：processed={stats.get('processed')} ok={origin_trace_ok} "
              f"partial={stats.get('partial')} not_found={stats.get('not_found')} "
              f"blocked={stats.get('blocked')} reason={stats.get('stoppedReason')} "
              f"elapsed={stats.get('elapsedMs')}ms")
        print(f"报告：{REPORT_PATH.relative_to(ROOT)}")
        print(f"交接：{handoff.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
