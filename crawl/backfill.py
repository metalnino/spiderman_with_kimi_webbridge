"""P4 详情按需回填：调用已开发详情能力补单条公告字段/摘要/附件。

路由（全部复用既有模块，不新写爬虫）：
- ccgp            → detail.fetch_detail（HTTP 直取，金额/招标人/代理/项目编号/截止时间）
- chinabidding    → tenderfile.fetch_tenderfile（桥模式；HTTP 详情 405 WAF 已废，正文可达/登录墙如实）
- ggzy / jsggzy   → tenderfile.fetch_tenderfile（ggzy_http 模式，正文摘要+附件）
- jiangsu_zhaobiao→ tenderfile.fetch_tenderfile（桥模式，含自动登录+附件；需桥在线）
- cebpub          → tenderfile.fetch_tenderfile（bridge_vaptcha；验证码未过登记待办并如实返回）

结果落库：字段列（amount/amount_text/buyer/agency/project_code/deadline/notice_type）、
summary / tenderfile_path / detail_status（成功=ok，失败=err:<摘要>）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from db import connect  # noqa: E402

from crawl.detail import fetch_detail, update_notice_detail  # noqa: E402
from crawl.origin import is_http_fetchable, resolve_origin  # noqa: E402
from crawl.tenderfile import fetch_tenderfile  # noqa: E402

FIELD_SOURCES = {"ccgp"}
SUMMARY_SOURCES = {"ggzy", "jsggzy", "jiangsu_zhaobiao", "cebpub", "chinabidding"}
# 原发寻址只对「可能转载」的聚合站行做（ccgp 自身即原发）
AGGREGATOR_SOURCES = {"chinabidding", "cebpub", "ggzy", "jsggzy", "jiangsu_zhaobiao"}


def _load_row(notice_id: int) -> dict | None:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, source_id, title, city, detail_url, official_url FROM notices WHERE id=%s",
                (notice_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def _save_result(notice_id: int, *, fields: dict | None = None,
                 summary: str | None = None, tenderfile_path: str | None = None,
                 detail_status: str | None = None, original_url: str | None = None,
                 origin_source: str | None = None) -> None:
    if fields:
        update_notice_detail(notice_id, fields)
    sets: list[str] = []
    params: list = []
    if summary is not None:
        sets.append("summary=%s")
        params.append(summary[:5000])
    if tenderfile_path is not None:
        sets.append("tenderfile_path=%s")
        params.append(tenderfile_path[:500])
    if detail_status is not None:
        sets.append("detail_status=%s")
        params.append(detail_status[:32])
    if original_url is not None:
        sets.append("original_url=%s")
        params.append(original_url[:1000])
    if origin_source is not None:
        sets.append("origin_source=%s")
        params.append(origin_source[:120])
    if not sets:
        return
    params.append(notice_id)
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE notices SET {', '.join(sets)} WHERE id=%s", tuple(params))
    finally:
        conn.close()


def _origin_from_summary(row: dict, summary_text: str | None) -> dict:
    """聚合站行：从摘要/正文找原发线索（来源行 URL/单位 + 主体映射）。"""
    if row.get("source_id") not in AGGREGATOR_SOURCES or not summary_text:
        return {}
    return resolve_origin(row.get("title") or "", summary_text)


def _parse_amount(amount_text: str | None) -> float | None:
    """采招详情金额文本（如 12.5万元 / 3000元）→ 元。"""
    if not amount_text:
        return None
    m = re.search(r"([\d,\.]+)\s*(万元|万|元)?", amount_text)
    if not m:
        return None
    try:
        num = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = m.group(2) or "元"
    if unit in ("万元", "万"):
        return num * 10000
    return num


def backfill_notice(notice_id: int) -> dict:
    """按需回填单条。所有失败如实返回 error，绝不编造。"""
    row = _load_row(notice_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    sid = row["source_id"]
    url = row["detail_url"] or row["official_url"]
    if not url:
        return {"ok": False, "error": "no_detail_url", "source_id": sid}

    if sid in FIELD_SOURCES:
        fields = fetch_detail(sid, url)
        err = fields.pop("_error", None) if isinstance(fields, dict) else None
        if not fields:
            reason = err or "fetch_failed"
            _save_result(notice_id, detail_status=f"err:{reason[:24]}")
            return {"ok": False, "error": reason, "source_id": sid}
        _save_result(notice_id, fields=fields, detail_status="ok")
        return {"ok": True, "source_id": sid, "fields": fields}

    if sid in SUMMARY_SOURCES:
        tf = fetch_tenderfile(sid, url)
        got = bool(tf.get("ok") and tf.get("tenderFile"))
        err = tf.get("error") or "fetch_failed"
        summary = None
        path = None
        if got:
            summary = (tf.get("summary") or (tf["tenderFile"].get("text") or "")[:2000])
            path = tf["tenderFile"].get("path")
        else:
            summary = tf.get("summary")  # 附件没拿到但正文摘要可达时仍留摘要
        # 结构化字段（ggzy/jsggzy b 页的项目编号/金额）
        tf_fields = tf.get("fields") or {}
        if tf_fields:
            _save_result(notice_id, fields=tf_fields)
        # 原发线索：详情抓取结构化 origin 优先，其次从摘要文本解析
        tf_origin = tf.get("origin") or {}
        origin = {}
        if not (tf_origin.get("source") or tf_origin.get("url")):
            origin = _origin_from_summary(row, summary)
        original_url = tf_origin.get("url") or origin.get("url")
        origin_source = tf_origin.get("source") or origin.get("entity")
        if not origin_source and isinstance(origin.get("platform"), dict):
            origin_source = origin["platform"].get("name")
        # 原发优先：命中可 HTTP 直取的官方域且与当前页不同 → 从原发取字段/摘要，失败兜底聚合站结果
        origin_result = None
        if original_url and original_url != url and is_http_fetchable(original_url):
            if "ccgp" in original_url:
                fields2 = fetch_detail("ccgp", original_url)
                fields2.pop("_error", None)
                if fields2:
                    _save_result(notice_id, fields=fields2)
                    origin_result = {"fields": fields2}
            else:
                tf2 = fetch_tenderfile("ggzy", original_url)
                if tf2.get("ok") and tf2.get("tenderFile"):
                    summary = tf2.get("summary") or (tf2["tenderFile"].get("text") or "")[:2000]
                    path = tf2["tenderFile"].get("path")
                    origin_result = {"summary": True, "tenderfile": True}
        _save_result(
            notice_id,
            summary=summary,
            tenderfile_path=path,
            detail_status="ok" if (got or summary) else f"err:{err[:24]}",
            original_url=original_url,
            origin_source=origin_source,
        )
        return {
            "ok": bool(got or summary),
            "source_id": sid,
            "summary": (summary or "")[:500],
            "tenderfile_path": path,
            "fields": tf_fields or None,
            "original_url": original_url,
            "origin_source": origin_source,
            "origin_fetched": origin_result,
            "error": None if (got or summary) else err,
        }

    return {"ok": False, "error": f"unknown_source:{sid}", "source_id": sid}
