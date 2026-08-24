"""P6 端到端：用真实江苏公告 + 已落盘真实附件（v3.2 真机下载）构造采集员格式交接物。

产物：data/trial/e2e_handoff.json（供解析员管道入口消费）。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from db import connect  # noqa: E402
from crawl.tenderfile import extract_text  # noqa: E402

TARGET_TITLE = "关于医院绿植租赁与养护服务采购公告"
TARGET_DOC = ROOT / "downloads" / "tenderfiles" / "jiangsu_zhaobiao" / "4b2a86716035c9e8.doc"


def main() -> None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT title, detail_url, official_url, publish_date, city, province, region_text "
                "FROM notices WHERE source_id='jiangsu_zhaobiao' AND title LIKE %s LIMIT 1",
                ("%" + TARGET_TITLE.split("采购公告")[0][2:] + "%",),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        raise SystemExit("target notice not found")
    if not TARGET_DOC.exists():
        raise SystemExit(f"tenderfile missing: {TARGET_DOC}")

    text = extract_text(TARGET_DOC, "doc")
    url = row["detail_url"] or row["official_url"] or ""
    item = {
        "title": row["title"],
        "platform": "jiangsu_zhaobiao",
        "url": url,
        "publishTime": (row["publish_date"].strftime("%Y-%m-%dT%H:%M:%S+08:00")
                        if row["publish_date"] else None),
        "region": row["city"] or row["province"] or row["region_text"],
        "amount": None,
        "summary": text[:200] if text else None,
        "dedupId": hashlib.md5((row["title"] + "jiangsu_zhaobiao" + url).encode("utf-8")).hexdigest(),
        "tenderFile": {
            "path": str(TARGET_DOC.relative_to(ROOT)).replace("\\", "/"),
            "text": text,
            "sourceUrl": None,
            "format": "docx",
        },
    }
    handoff = {
        "runId": "collector-e2e-20260824",
        "implements": "collector/v1.2.0",
        "generatedAt": "2026-08-24T00:00:00",
        "items": [item],
    }
    out = ROOT / "data" / "trial" / "e2e_handoff.json"
    out.write_text(json.dumps(handoff, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", out, "| text chars:", len(text))


if __name__ == "__main__":
    main()
