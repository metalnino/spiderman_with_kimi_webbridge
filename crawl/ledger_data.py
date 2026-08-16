"""Read-only ledger queries for local API (MySQL → JSON-ready dicts)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect  # noqa: E402

from crawl.filters import PROVINCE_CITY, source_capability_hint
from crawl.sources import enabled_source_ids

NEW_HOURS = 48
MAX_LIMIT = 200


def _jsonable(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace")
    return v


def _rows(sql: str, args=()) -> list[dict]:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            rows = list(cur.fetchall())
            return [{k: _jsonable(v) for k, v in r.items()} for r in rows]
    finally:
        conn.close()


def _one(sql: str, args=()) -> Any:
    rows = _rows(sql, args)
    if not rows:
        return None
    return next(iter(rows[0].values()))


def clamp_limit(raw: Any, default: int = 50) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = default
    return max(1, min(n, MAX_LIMIT))


def clamp_offset(raw: Any) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 0
    return max(0, n)


def meta() -> dict:
    return {
        "province_city": PROVINCE_CITY,
        "sources": enabled_source_ids(),
        "new_hours": NEW_HOURS,
        "hints": {s: source_capability_hint(s) for s in ("chinabidding", "cebpub")},
    }


def summary() -> dict:
    notice_total = int(_one("SELECT COUNT(*) AS c FROM notices") or 0)
    run_total = int(_one("SELECT COUNT(*) AS c FROM crawl_runs") or 0)
    entity_total = int(_one("SELECT COUNT(*) AS c FROM entities") or 0)
    open_todos = int(_one("SELECT COUNT(*) AS c FROM captcha_todos WHERE status='open'") or 0)
    by_source = _rows(
        "SELECT source_id, COUNT(*) AS c FROM notices GROUP BY source_id ORDER BY c DESC"
    )
    by_clean = _rows(
        "SELECT COALESCE(clean_status,'-') AS clean_status, COUNT(*) AS c "
        "FROM notices GROUP BY clean_status ORDER BY c DESC"
    )
    recent_new = int(
        _one(
            "SELECT COUNT(*) AS c FROM notices WHERE created_at >= (NOW() - INTERVAL %s HOUR)",
            (NEW_HOURS,),
        )
        or 0
    )
    return {
        "notice_total": notice_total,
        "run_total": run_total,
        "entity_total": entity_total,
        "open_captcha": open_todos,
        "recent_new": recent_new,
        "by_source": by_source,
        "by_clean": by_clean,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


NOTICE_SELECT = (
    "id, title, source_id, source_name, city, province, keyword, publish_date, "
    "created_at, detail_url, official_url, clean_status, clean_reason, manual_label, "
    "amount, amount_text, buyer, agency, project_code, read_at, lead_status, amount_status, remark"
)

_SORTS = {
    "created": "created_at DESC",
    "amount": "amount IS NULL, amount DESC",
    "publish": "publish_date IS NULL, publish_date DESC",
}


def _build_notices_where(
    source_id=None, province=None, city=None, clean_status=None, only_pass=False,
    q=None, lead_status=None, amount_min=None, amount_max=None,
) -> tuple[str, list[Any]]:
    where = ["1=1"]
    args: list[Any] = []
    if source_id:
        where.append("source_id=%s")
        args.append(source_id)
    if city:
        where.append("city=%s")
        args.append(city)
    elif province:
        cities = PROVINCE_CITY.get(province) or []
        if cities:
            placeholders = ",".join(["%s"] * len(cities))
            where.append(f"(province=%s OR city IN ({placeholders}))")
            args.append(province)
            args.extend(cities)
        else:
            where.append("province=%s")
            args.append(province)
    if clean_status:
        where.append("clean_status=%s")
        args.append(clean_status)
    if only_pass:
        where.append("(clean_status IS NULL OR clean_status<>'drop')")
        where.append("(manual_label IS NULL OR manual_label<>'irrelevant')")
    if lead_status:
        where.append("lead_status=%s")
        args.append(lead_status)
    if amount_min is not None:
        where.append("amount >= %s")
        args.append(amount_min)
    if amount_max is not None:
        where.append("amount <= %s")
        args.append(amount_max)
    if q:
        where.append("title LIKE %s")
        args.append(f"%{q}%")
    return " AND ".join(where), args


def notices(
    *,
    source_id: str | None = None,
    province: str | None = None,
    city: str | None = None,
    clean_status: str | None = None,
    only_pass: bool = False,
    q: str | None = None,
    lead_status: str | None = None,
    amount_min: float | None = None,
    amount_max: float | None = None,
    sort: str = "created",
    limit: int = 50,
    offset: int = 0,
) -> dict:
    limit = clamp_limit(limit)
    offset = clamp_offset(offset)
    wsql, args = _build_notices_where(source_id, province, city, clean_status, only_pass, q, lead_status, amount_min, amount_max)
    order = _SORTS.get(sort, _SORTS["created"])
    total = int(_one(f"SELECT COUNT(*) AS c FROM notices WHERE {wsql}", tuple(args)) or 0)
    rows = _rows(
        f"SELECT {NOTICE_SELECT} FROM notices WHERE {wsql} ORDER BY {order} LIMIT %s OFFSET %s",
        tuple(args) + (limit, offset),
    )
    cutoff = datetime.now() - timedelta(hours=NEW_HOURS)
    for r in rows:
        ca = r.get("created_at")
        is_new = False
        if isinstance(ca, str):
            try:
                is_new = datetime.strptime(ca, "%Y-%m-%d %H:%M:%S") >= cutoff
            except ValueError:
                is_new = False
        r["is_new"] = is_new
        r["capability_hint"] = source_capability_hint(r.get("source_id") or "")
    return {"total": total, "limit": limit, "offset": offset, "items": rows}


def export_csv(**filters) -> str:
    import csv
    import io

    wsql, args = _build_notices_where(
        filters.get("source_id"), filters.get("province"), filters.get("city"),
        filters.get("clean_status"), filters.get("only_pass"), filters.get("q"),
        filters.get("lead_status"), filters.get("amount_min"), filters.get("amount_max"),
    )
    order = _SORTS.get(filters.get("sort"), _SORTS["created"])
    rows = _rows(f"SELECT {NOTICE_SELECT} FROM notices WHERE {wsql} ORDER BY {order} LIMIT 5000", tuple(args))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "标题", "源站", "城市", "省", "关键词", "发布时间", "首次发现", "金额(元)", "金额文本",
                "招标人", "代理", "项目编号", "处理状态", "金额确认", "已读", "详情链接", "原文链接"])
    for r in rows:
        w.writerow([
            r.get("id"), r.get("title"), r.get("source_id"), r.get("city"), r.get("province"),
            r.get("keyword"), r.get("publish_date"), r.get("created_at"), r.get("amount"),
            r.get("amount_text"), r.get("buyer"), r.get("agency"), r.get("project_code"),
            r.get("lead_status"), r.get("amount_status"), r.get("read_at"),
            r.get("detail_url"), r.get("official_url"),
        ])
    return "﻿" + buf.getvalue()


def runs(limit: int = 40) -> dict:
    limit = clamp_limit(limit, 40)
    items = _rows(
        "SELECT id, source_id, status, item_count, note, started_at, finished_at "
        "FROM crawl_runs ORDER BY id DESC LIMIT %s",
        (limit,),
    )
    return {"items": items}


def clean_stats() -> dict:
    decisions = _rows(
        "SELECT decision, COUNT(*) AS c FROM clean_events "
        "WHERE created_at >= (NOW() - INTERVAL 7 DAY) GROUP BY decision"
    )
    drop_reasons = _rows(
        "SELECT reason, COUNT(*) AS c FROM clean_events WHERE decision='drop' "
        "GROUP BY reason ORDER BY c DESC LIMIT 15"
    )
    return {"decisions_7d": decisions, "drop_reasons": drop_reasons}


def keywords() -> dict:
    return {
        "items": _rows(
            "SELECT keyword, enabled, group_name FROM keyword_state ORDER BY enabled DESC, keyword"
        )
    }


def captcha(limit: int = 40) -> dict:
    limit = clamp_limit(limit, 40)
    from crawl import cookie_store

    items = _rows(
        "SELECT id, source_id, detail_url, title, status, note, created_at FROM captcha_todos "
        "ORDER BY FIELD(status,'open','closed'), id DESC LIMIT %s",
        (limit,),
    )
    for it in items:
        st = cookie_store.status(it.get("source_id") or "")
        it["has_saved_cookie"] = st.get("has_cookie")
        it["cookie_saved_at"] = st.get("saved_at")
    return {"items": items}


def entities(limit: int = 100) -> dict:
    import json as _json

    limit = clamp_limit(limit, 100)
    items = _rows(
        "SELECT id, name, entity_type, city, province, notice_count, last_notice_at, next_bid_hint, meta_json "
        "FROM entities ORDER BY notice_count DESC, id DESC LIMIT %s",
        (limit,),
    )
    for it in items:
        meta = it.get("meta_json")
        tags = []
        if isinstance(meta, str):
            try:
                meta = _json.loads(meta)
            except Exception:
                meta = None
        if isinstance(meta, dict):
            tags = meta.get("service_tags") or []
        it["service_tags"] = tags
        it.pop("meta_json", None)
    return {"items": items}
