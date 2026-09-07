"""实体情报员最小运行入口 —— 契约 input → 契约 output + 观测报告 + 管道交接物。

用法:
  python scripts/intel_run.py                       # 无输入：全量累积库聚合 + 抽取中标企业
  python scripts/intel_run.py input.json            # 读契约 input JSON 文件
  python scripts/intel_run.py -                     # 从 stdin 读契约 input JSON
  python scripts/intel_run.py -o out.json ...       # output 同时落盘到指定路径

stdout 打印 {ok, employee, implements, output, reportPath, metrics, handoffPath}；
观测报告落 reports/intel-report.json（契约 observability.reportPath）。

管道交接物（P6 接线）：每轮自动写
  handoffs/intel/latest.json                        # 下游（如 CRM/分析层）读取的最新实体图
  handoffs/intel/<runId>.json                       # 按 runId 归档留痕
字段：{runId, implements, generatedAt, entities, winners, relations}。
环境变量 SPIDER_INTEL_HANDOFF_DIR 可重定向（测试用）。

退出码: 0 成功；2 契约 input 校验失败；1 其他错误。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crawl.intel_employee import IMPLEMENTS, IDENTITY, ContractInputError, run  # noqa: E402

HANDOFF_DIR = Path(os.environ.get("SPIDER_INTEL_HANDOFF_DIR") or (ROOT / "handoffs" / "intel"))


def _write_handoff(result: dict) -> str:
    """落盘管道交接物：latest.json + runId 归档。返回 latest 路径。"""
    HANDOFF_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "runId": result["report"]["runId"],
        "implements": IMPLEMENTS,
        "generatedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "entities": result["output"]["entities"],
        "winners": result["output"]["winners"],
        "relations": result["output"]["relations"],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    (HANDOFF_DIR / f"{result['report']['runId']}.json").write_text(text, encoding="utf-8")
    latest = HANDOFF_DIR / "latest.json"
    latest.write_text(text, encoding="utf-8")
    return str(latest)


def main() -> int:
    ap = argparse.ArgumentParser(description="实体情报员（implements: entity_intel/v1.0.0）")
    ap.add_argument("input", nargs="?", default=None, help="契约 input JSON 路径；'-' 为 stdin；缺省全量")
    ap.add_argument("-o", "--output", default=None, help="output 落盘路径（缺省只打 stdout）")
    ap.add_argument("--no-handoff", action="store_true", help="跳过管道交接物落盘（调试用）")
    args = ap.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    inp = None
    if args.input == "-":
        raw = sys.stdin.read()
        inp = json.loads(raw) if raw.strip() else None
    elif args.input:
        inp = json.loads(Path(args.input).read_text(encoding="utf-8"))

    try:
        result = run(inp)
    except ContractInputError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False, indent=2))
        return 2
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"unexpected: {type(e).__name__}: {e}"}, ensure_ascii=False, indent=2))
        return 1

    if args.output:
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(result["output"], ensure_ascii=False, indent=2), encoding="utf-8")

    handoff_path = None
    if not args.no_handoff:
        handoff_path = _write_handoff(result)

    print(json.dumps(
        {
            "ok": True,
            "employee": IDENTITY["name"],
            "implements": IMPLEMENTS,
            "output": result["output"],
            "reportPath": result["reportPath"],
            "handoffPath": handoff_path,
            "metrics": result["report"]["metrics"],
        },
        ensure_ascii=False,
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    sys.exit(main())
