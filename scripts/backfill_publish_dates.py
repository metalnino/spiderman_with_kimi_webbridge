"""补录 notices.publish_date：对 publish_date 为空的记录，从源站详情页取「信息发布时间」。

背景（2026-08-26 审计）：jsggzy 省站搜索 API 的 webdate/publishTime 字段不存在，
实际字段为 infodatepx（= 详情页「信息发布时间」）。历史入库的 20 条 jsggzy 记录因此
publish_date 为 NULL。注意：详情页 URL 中的 8 位日期段与 infodate 字段可能是「入库/
重发日期」，比真实发布时间晚（如 URL 20200921、真实 2020-05-07），不可用作补录来源。

本脚本只做「详情页实证 → 标题核对 → 补录」，拿不到证据就保持 NULL（不造假）。
默认 dry-run；--apply 才写库。结果写 data/backfill_publish_report.json。
"""
from __future__ import annotations

import argparse
import json
import re
import ssl
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect  # noqa: E402

CTX = ssl._create_unverified_context()
HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
REPORT = ROOT / "data" / "backfill_publish_report.json"

# 页面「信息发布时间」的多种标签写法（按优先级）
DATE_PATTERNS = [
    r"信息发布时间[：:\s]*([0-9]{4}[-/年][0-9]{1,2}[-/月][0-9]{1,2}日?\s*[0-9:]{0,8})",
    r"发布时间[：:\s]*([0-9]{4}[-/年][0-9]{1,2}[-/月][0-9]{1,2}日?\s*[0-9:]{0,8})",
    r"公告日期[：:\s]*([0-9]{4}[-/年][0-9]{1,2}[-/月][0-9]{1,2}日?\s*[0-9:]{0,8})",
]
TITLE_PATTERNS = [
    r'<h2[^>]*class="[^"]*ewb-trade-h[^"]*"[^>]*>(.*?)</h2>',
    r"<h1[^>]*>(.*?)</h1>",
]
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[\s\u3000\t\u00a0]")


def norm(s: str | None) -> str:
    return WS_RE.sub("", TAG_RE.sub("", s or ""))


def parse_datetime(raw: str) -> str | None:
    """'2020年5月7日 03:05:34' / '2020-05-07 11:04:36' → 'YYYY-MM-DD HH:MM:SS'。"""
    s = raw.strip().replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-")
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$", s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh = int(m.group(4) or 0)
    mi = int(m.group(5) or 0)
    ss = int(m.group(6) or 0)
    try:
        return datetime(y, mo, d, hh, mi, ss).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def fetch_page(url: str) -> tuple[str | None, str | None]:
    """返回 (规范化页面标题, 发布时间文本)；拿不到返回 (None, None)。"""
    req = urllib.request.Request(url, headers=HDRS)
    with urllib.request.urlopen(req, timeout=25, context=CTX) as resp:
        html = resp.read().decode("utf-8", "ignore")
    page_title = None
    for pat in TITLE_PATTERNS:
        m = re.search(pat, html, re.S)
        if m:
            page_title = norm(m.group(1))
            break
    pub = None
    for pat in DATE_PATTERNS:
        m = re.search(pat, html)
        if m:
            pub = m.group(1)
            break
    return page_title, pub


def main() -> None:
    ap = argparse.ArgumentParser(description="补录 publish_date（默认 dry-run）")
    ap.add_argument("--apply", action="store_true", help="真正写库（默认只演练）")
    ap.add_argument("--id", type=int, default=0, help="只处理指定 notices.id")
    args = ap.parse_args()

    conn = connect()
    try:
        with conn.cursor() as cur:
            if args.id:
                cur.execute(
                    "SELECT id, source_id, title, detail_url FROM notices "
                    "WHERE publish_date IS NULL AND id=%s",
                    (args.id,),
                )
            else:
                cur.execute(
                    "SELECT id, source_id, title, detail_url FROM notices "
                    "WHERE publish_date IS NULL ORDER BY id",
                )
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

    report = {"dry_run": not args.apply, "total": len(rows), "results": []}
    for r in rows:
        entry = {"id": r["id"], "source_id": r["source_id"], "title": r["title"]}
        url = r.get("detail_url")
        if not url:
            entry["status"] = "skip_no_url"
            report["results"].append(entry)
            continue
        try:
            page_title, pub = fetch_page(url)
        except Exception as e:  # noqa: BLE001 —— 如实记录，不编造
            entry["status"] = "fetch_failed"
            entry["error"] = type(e).__name__
            report["results"].append(entry)
            print(f"id={r['id']} fetch_failed {type(e).__name__}", flush=True)
            continue
        entry["page_pub"] = pub
        if not pub:
            entry["status"] = "no_date_on_page"
            report["results"].append(entry)
            continue
        dt = parse_datetime(pub)
        if not dt:
            entry["status"] = "bad_date_format"
            report["results"].append(entry)
            continue
        if page_title and norm(r["title"]) != page_title:
            entry["status"] = "title_mismatch"
            entry["page_title"] = page_title[:120]
            report["results"].append(entry)
            continue
        entry["publish_date"] = dt
        entry["status"] = "filled" if args.apply else "would_fill"
        if args.apply:
            conn = connect()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE notices SET publish_date=%s WHERE id=%s AND publish_date IS NULL",
                        (dt, r["id"]),
                    )
                    entry["updated"] = cur.rowcount
            finally:
                conn.close()
        report["results"].append(entry)
        print(f"id={r['id']} {entry['status']} pub={entry.get('publish_date') or entry.get('page_pub') or ''}",
              flush=True)

    filled = sum(1 for e in report["results"] if e["status"] in ("filled", "would_fill"))
    report["fillable"] = filled
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(
        {"total": report["total"], "fillable": filled, "dry_run": not args.apply,
         "report": str(REPORT)}, ensure_ascii=False))
    for e in report["results"]:
        print(f"id={e['id']} {e['status']} pub={e.get('publish_date') or e.get('page_pub') or ''} "
              f"{e.get('error') or ''} {e.get('page_title') or ''}")


if __name__ == "__main__":
    main()
