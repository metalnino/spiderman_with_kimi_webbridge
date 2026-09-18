"""P4 详情按需回填：调用已开发详情能力补单条公告字段/摘要/附件。

路由（全部复用既有模块，不新写爬虫）：
- ccgp            → detail.fetch_detail（HTTP 直取，金额/招标人/代理/项目编号/截止时间）
- chinabidding    → tenderfile.fetch_tenderfile（桥模式；HTTP 详情 405 WAF 已废，正文可达/登录墙如实）
- ggzy / jsggzy   → tenderfile.fetch_tenderfile（ggzy_http 模式，正文摘要+附件）
- jiangsu_zhaobiao→ tenderfile.fetch_tenderfile（桥模式，含自动登录+附件；需桥在线）
- cebpub          → tenderfile.fetch_tenderfile（bridge_vaptcha；验证码未过登记待办并如实返回）
- yfbzb           → tenderfile.fetch_tenderfile（http 一级直通详情正文；无附件时仍留 page_summary）
- qianlima        → tenderfile.fetch_tenderfile（bridge；bid-<id>.html 419 反爬，桥渲染正文）
- tgnet           → tenderfile.fetch_tenderfile（bridge；项目详情页桥渲染，列表型正文如实返回）

结果落库：字段列（amount/amount_text/buyer/agency/project_code/deadline/notice_type）、
summary / tenderfile_path / detail_status（成功=ok，失败=err:<摘要>）。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from db import connect  # noqa: E402

from crawl import ai_extract  # noqa: E402
from crawl import origin_search  # noqa: E402
from crawl.detail import fetch_detail, update_notice_detail  # noqa: E402
from crawl.origin import fetch_route_for, resolve_origin  # noqa: E402
from crawl.tenderfile import fetch_tenderfile  # noqa: E402

FIELD_SOURCES = {"ccgp"}
# 详情正文/附件回填路由（fetch_tenderfile 按 DETAIL_MODES 派发）：
#   ggzy/jsggzy=ggzy_http、jiangsu_zhaobiao/chinabidding=bridge、cebpub=bridge_vaptcha、
#   yfbzb=http（一级直通详情正文）、qianlima=bridge（bid-<id>.html 419→桥）、tgnet=bridge（项目详情桥渲染）
SUMMARY_SOURCES = {
    "ggzy", "jsggzy", "jiangsu_zhaobiao", "cebpub", "chinabidding",
    "yfbzb", "qianlima", "tgnet", "szexgrp",
}
# 原发寻址只对「可能转载」的聚合站行做（ccgp/yfbzb 自身即原发；tgnet/qianlima 列表型无需寻址）
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
                 origin_source: str | None = None, ai_fields: dict | None = None) -> None:
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
    if ai_fields is not None:
        sets.append("ai_fields=%s")
        params.append(json.dumps(ai_fields, ensure_ascii=False))
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


_CN_DEADLINE_RE = re.compile(r"(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")


def _norm_deadline(v) -> str | None:
    """AI 抽的 deadline 可能是「2026年8月27日」等中文格式 → 归一化为 MySQL DATETIME 可接受格式；失败返回 None（丢弃，不写坏列）。"""
    s = str(v or "").strip()
    if not s:
        return None
    if re.fullmatch(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}([ T]\d{1,2}:\d{2}(:\d{2})?)?", s):
        return s[:19].replace("/", "-")
    m = _CN_DEADLINE_RE.search(s)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d} 00:00:00"
    return None


def find_notice_id_by_item(item: dict) -> int | None:
    """契约条目 → notices.id（按 source_id+title+url 回查；找不到返回 None）。"""
    title = item.get("title") or ""
    url = item.get("url") or ""
    if not title or not url:
        return None
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM notices WHERE source_id=%s AND title=%s "
                "AND (detail_url=%s OR official_url=%s) LIMIT 1",
                (item.get("platform"), title, url, url),
            )
            row = cur.fetchone()
            return int(row["id"]) if row else None
    finally:
        conn.close()


def auto_backfill_pass(output_items: list[dict], run_list: list[str],
                       *, per_source_limit: int = 5) -> dict:
    """P7 出勤后自动回填：对「可投标阶段、缺金额」的 HTTP 详情源站新条目补字段/摘要。

    只碰 ccgp/ggzy/jsggzy（HTTP 直取、无人工门）；每条一次、每站每轮上限 5；
    失败如实记（detail_status），不轰炸不阻塞出勤。SPIDER_NO_AUTO_BACKFILL=1 关闭。
    """
    if os.environ.get("SPIDER_NO_AUTO_BACKFILL"):
        return {"enabled": False}
    actionable = ("intent", "bidding", "change")
    stats = {"enabled": True, "attempted": 0, "filled": 0, "failed": 0, "per_source": {}}
    for pid in run_list:
        if pid not in ("ccgp", "ggzy", "jsggzy"):
            continue
        per = {"attempted": 0, "filled": 0}
        for it in output_items:
            if per["attempted"] >= per_source_limit:
                break
            if it.get("platform") != pid:
                continue
            if it.get("amount") is not None:
                continue  # 已有金额：无需回填
            stage = it.get("notice_stage") or ""
            if stage not in actionable:
                continue  # 只回填可投标线索（结果公告等历史不优先）
            nid = find_notice_id_by_item(it)
            if not nid:
                continue
            per["attempted"] += 1
            stats["attempted"] += 1
            try:
                out = backfill_notice(nid)
            except Exception as e:  # noqa: BLE001 —— 单条异常不炸出勤
                out = {"ok": False, "error": str(e)[:120]}
            if out.get("ok"):
                per["filled"] += 1
                stats["filled"] += 1
                it["amount"] = out.get("fields", {}).get("amount") or it.get("amount")
            else:
                stats["failed"] += 1
        stats["per_source"][pid] = per
    return stats


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
        summary = fields.pop("summary", None) if isinstance(fields, dict) else None
        if not fields:
            reason = err or "fetch_failed"
            _save_result(notice_id, detail_status=f"err:{reason[:24]}")
            return {"ok": False, "error": reason, "source_id": sid}
        _save_result(notice_id, fields=fields, summary=summary, detail_status="ok")
        return {"ok": True, "source_id": sid, "fields": fields, "summary": summary}

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
        mode = fetch_route_for(original_url) if (original_url and original_url != url) else None
        if mode == "ccgp_http":
            fields2 = fetch_detail("ccgp", original_url)
            fields2.pop("_error", None)
            if fields2:
                _save_result(notice_id, fields=fields2)
                origin_result = {"fields": fields2}
        elif mode == "ggzy_http":
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


def _load_summary_fields(notice_id: int) -> dict | None:
    """读取单条公告的 summary + 关键字段（供 AI 抽取兜底）。"""
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, summary, buyer, agency, amount_text, deadline, winner FROM notices WHERE id=%s",
                (notice_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        conn.close()


def ai_enrich_notice(notice_id: int, *, fields=None) -> dict:
    """对单条公告用 AI 抽取字段兜底（规则抓不到的字段）。

    输入 summary（详情正文），输出结构化字段；只回填「规则还没拿到」的字段，
    绝不用 AI 覆盖规则结果。返回 {ok, ai_fields, filled}；
    无 summary / AI 禁用 / 抽取空 → 如实返回，不造假。
    """
    row = _load_summary_fields(notice_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    summary = row.get("summary") or ""
    if not summary:
        return {"ok": False, "error": "no_summary"}
    ai = ai_extract.extract_fields(summary, fields)
    if not ai:
        _save_result(notice_id, ai_fields={})
        return {"ok": False, "error": "ai_empty_or_disabled", "ai_fields": {}}
    # 只补规则缺失的字段，不覆盖
    updates = {}
    for k, v in ai.items():
        if v and not row.get(k):
            if k == "deadline":
                iso = _norm_deadline(v)
                if not iso:
                    continue  # 中文/非标日期归一化不了就丢弃，不写坏 DATETIME 列
                updates[k] = iso
            else:
                updates[k] = v
    if updates:
        update_notice_detail(notice_id, updates)
    _save_result(notice_id, ai_fields=ai)
    return {"ok": True, "ai_fields": ai, "filled": sorted(updates.keys())}


def enrich_from_ggzy(notice_id: int) -> dict:
    """登录墙公告 → ggzy 站内检索 → b-page 转爬 → 回填采购人/金额/中标 + 原发。

    聚合站（chinabidding/cebpub）详情在登录墙/验证码墙后，但同一公告在 ggzy（全国公共资源
    交易平台）原发且开放。用标题去 ggzy 检索 → 匹配 → 抓 b-page（开放）→ 回填字段。
    找不到匹配/抓取失败 → 如实返回，绝不编造。
    """
    row = _load_row(notice_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    kw = origin_search.search_keyword(row["title"])
    results = origin_search.search_ggzy(kw, max_results=5)
    match = origin_search.match_ggzy(row["title"], results)
    if not match:
        return {"ok": False, "error": "no_ggzy_match", "keyword": kw, "candidates": len(results)}
    tf = fetch_tenderfile("ggzy", match["url"])
    fields = tf.get("fields") or {}
    updates = {k: v for k, v in fields.items() if v}
    if updates:
        update_notice_detail(notice_id, updates)
    _save_result(
        notice_id,
        fields=updates or None,
        original_url=match["url"],
        origin_source=(tf.get("origin") or {}).get("source") or "全国公共资源交易平台",
        detail_status=("ok" if tf.get("ok") else f"origin:{str(tf.get('error') or '')[:20]}"),
    )
    return {"ok": True, "keyword": kw, "matched_title": match["title"], "url": match["url"], "fields": fields}
