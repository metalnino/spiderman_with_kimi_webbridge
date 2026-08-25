"""千里马代理验证探针（谨慎：单关键词单页，只读不写库）。

用法: python scripts/probe_qianlima_proxy.py
前置: config/proxy.json per_source.qianlima 填好代理（或设环境变量 SPIDER_PROXY）。
结果: data/qianlima_proxy_probe.json（证据）+ 控制台摘要。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["SPIDER_QIANLIMA_MAX_PAGES"] = "1"

from crawl.config_loader import proxy_for  # noqa: E402
from crawl.sources.qianlima import QianlimaSource  # noqa: E402
from crawl.sources.base import SourceError  # noqa: E402

OUT = ROOT / "data" / "qianlima_proxy_probe.json"


def mask(proxy: str) -> str:
    if "@" in proxy:
        return proxy.split("@", 1)[1]
    return proxy


def main() -> None:
    report: dict = {}
    proxy = proxy_for("qianlima")
    if not proxy:
        report["ok"] = False
        report["error"] = "no_proxy_configured"
        report["hint"] = "在 config/proxy.json 的 per_source.qianlima 填入代理串（http://ip:port），或设环境变量 SPIDER_PROXY"
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return
    report["proxy"] = mask(proxy)
    src = QianlimaSource()
    try:
        items = list(src.fetch(["绿植租摆"], max_pages=1))
        report["ok"] = True
        report["count"] = len(items)
        report["sample"] = [
            {"t": n.title, "d": (n.publish_date or "")[:10], "city": n.city} for n in items[:8]
        ]
    except SourceError as e:
        report["ok"] = False
        report["error"] = str(e)[:400]
        report["partial"] = len(e.partial)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "sample"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
