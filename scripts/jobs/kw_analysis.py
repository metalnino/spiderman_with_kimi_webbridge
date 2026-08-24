"""关键词库只读分析：配置分组 + DB keyword_state + notices 按词计数 + 新词标题命中探针。

用法: python scripts/jobs/kw_analysis.py [--out data/kw_analysis_out.json]
输出: 结构化 JSON 报告（默认 data/kw_analysis_out.json）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect  # noqa: E402


def build_report() -> dict:
    out: dict = {}
    cfg = json.loads((ROOT / "config" / "crawl_config.json").read_text(encoding="utf-8"))
    kw_cfg = cfg["keywords"]
    out["config_groups"] = {g: list(v) for g, v in kw_cfg.items() if g != "notes"}

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT keyword, enabled, group_name FROM keyword_state ORDER BY enabled DESC, keyword")
            out["db_keyword_state"] = [dict(r) for r in cur.fetchall()]
            cur.execute(
                "SELECT keyword, COUNT(*) AS c, SUM(clean_status='pass') AS pass_cnt "
                "FROM notices GROUP BY keyword ORDER BY c DESC"
            )
            out["notice_counts"] = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT COUNT(*) AS c FROM notices")
            out["total_notices"] = cur.fetchone()["c"]
            for phrase in ("办公绿化", "职场绿植", "办公区绿化", "办公场所绿化"):
                cur.execute("SELECT COUNT(*) AS c FROM notices WHERE title LIKE %s", (f"%{phrase}%",))
                out.setdefault("title_hits", {})[phrase] = cur.fetchone()["c"]
    finally:
        conn.close()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data" / "kw_analysis_out.json"))
    args = ap.parse_args()
    report = build_report()
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    enabled = [r["keyword"] for r in report["db_keyword_state"] if r["enabled"]]
    print(f"enabled={enabled} notices={report['total_notices']} -> {args.out}")


if __name__ == "__main__":
    main()
