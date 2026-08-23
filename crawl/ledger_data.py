"""Read-only ledger queries for local API (MySQL → JSON-ready dicts)."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect  # noqa: E402

from crawl.config_loader import target_city_names
from crawl.filters import PROVINCE_CITY, source_capability_hint
from crawl.sources import enabled_source_ids
from crawl.stage import STAGE_LABELS, STAGES  # noqa: E402

NEW_HOURS = 48
MAX_LIMIT = 200
MAX_FOLD_ROWS = 2000  # 折叠在 Python 侧做：单次最多拉取的原始行数（超过则截断并提示）


def _norm_title(t: str | None) -> str:
    """跨站折叠用的标题规范化：去空白/全角空格/制表符/不换行空格。"""
    return re.sub(r"[\s\u3000\t\u00a0]", "", t or "")


# 与 _norm_title 等价的 SQL 表达式（用于 GROUP BY 总数统计）
# 注意：不能用 CHAR(0x00A0)/CONVERT 构造——二进制字节当 UTF-8 解析会返回 NULL；
# 直接用 Unicode 字面量，pymysql 以 utf8mb4 发送即可匹配。
_FOLD_SQL = "TRIM(REPLACE(REPLACE(REPLACE(REPLACE(title,' ',''),'\u3000',''),'\\t',''),'\u00a0',''))"


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
        "stages": [{"key": k, "label": lbl} for k, _rank, lbl, _words in STAGES],
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
    "amount, amount_text, buyer, agency, project_code, read_at, lead_status, amount_status, "
    "remark, notice_stage, stage_rank"
)

_SORTS = {
    "created": "created_at DESC",
    "amount": "amount IS NULL, amount DESC",
    "publish": "publish_date IS NULL, publish_date DESC",
}


def _build_notices_where(
    source_id=None, province=None, city=None, clean_status=None, only_pass=False,
    q=None, lead_status=None, amount_min=None, amount_max=None, target_only=False,
    stage=None,
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
    if target_only:
        names = target_city_names()
        if names:
            placeholders = ",".join(["%s"] * len(names))
            where.append(f"city IN ({placeholders})")
            args.extend(names)
    if q:
        where.append("title LIKE %s")
        args.append(f"%{q}%")
    if stage:
        where.append("notice_stage=%s")
        args.append(stage)
    return " AND ".join(where), args


def _fold_notices(rows: list[dict], sort: str) -> list[dict]:
    """跨站视图折叠：同规范化标题 + 同城 → 一条主行（多源标注）。

    主行选择：有金额者优先，其次发布时间早者，最后 id 小者。
    折叠只发生在结果集内部（随筛选动态变化），不动存储。
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for r in rows:
        key = (_norm_title(r.get("title")), r.get("city") or "")
        groups.setdefault(key, []).append(r)

    folded: list[dict] = []
    for members in groups.values():
        if len(members) == 1:
            folded.append(members[0])
            continue
        members_sorted = sorted(
            members,
            key=lambda m: (
                m.get("amount") is None,  # 有金额的排前
                not (m.get("publish_date") or ""),  # 有发布时间的排前
                m.get("publish_date") or "",
                m.get("id") or 0,
            ),
        )
        primary = members_sorted[0]
        primary["dup_count"] = len(members)
        primary["sources"] = sorted({m.get("source_id") for m in members if m.get("source_id")})
        primary["duplicates"] = [
            {
                "id": m.get("id"),
                "source_id": m.get("source_id"),
                "source_name": m.get("source_name"),
                "detail_url": m.get("detail_url"),
                "official_url": m.get("official_url"),
                "publish_date": m.get("publish_date"),
            }
            for m in members_sorted[1:]
        ]
        folded.append(primary)

    if sort == "publish":
        folded.sort(key=lambda r: (not (r.get("publish_date") or ""), r.get("publish_date") or ""), reverse=True)
    elif sort == "amount":
        folded.sort(key=lambda r: (r.get("amount") is None, -(r.get("amount") or 0)))
    else:
        folded.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return folded


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
    target_only: bool = False,
    stage: str | None = None,
) -> dict:
    limit = clamp_limit(limit)
    offset = clamp_offset(offset)
    wsql, args = _build_notices_where(
        source_id, province, city, clean_status, only_pass, q,
        lead_status, amount_min, amount_max, target_only, stage,
    )
    order = _SORTS.get(sort, _SORTS["created"])
    total = int(
        _one(
            f"SELECT COUNT(*) AS c FROM (SELECT 1 AS one FROM notices WHERE {wsql} "
            f"GROUP BY {_FOLD_SQL}, IFNULL(city,'')) x",
            tuple(args),
        )
        or 0
    )
    rows = _rows(
        f"SELECT {NOTICE_SELECT} FROM notices WHERE {wsql} ORDER BY {order} LIMIT {MAX_FOLD_ROWS}",
        tuple(args),
    )
    truncated = len(rows) >= MAX_FOLD_ROWS
    folded = _fold_notices(rows, sort)
    items = folded[offset:offset + limit]
    cutoff = datetime.now() - timedelta(hours=NEW_HOURS)
    for r in items:
        ca = r.get("created_at")
        is_new = False
        if isinstance(ca, str):
            try:
                is_new = datetime.strptime(ca, "%Y-%m-%d %H:%M:%S") >= cutoff
            except ValueError:
                is_new = False
        r["is_new"] = is_new
        r["capability_hint"] = source_capability_hint(r.get("source_id") or "")
        st = r.get("notice_stage")
        r["stage_label"] = STAGE_LABELS.get(st, st or "其他")
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
        "folded": True,
        "truncated": truncated,
    }


FULL_NOTICE_SELECT = (
    "id, source_id, source_name, external_id, title, publish_date, open_time, deadline, "
    "province, city, region_text, keyword, notice_stage, stage_rank, bid_status, "
    "clean_status, clean_reason, manual_label, read_at, lead_status, amount_status, "
    "remark, amount, amount_text, buyer, agency, project_code, notice_type, "
    "detail_url, official_url, project_key, project_name, summary, tenderfile_path, "
    "detail_status, created_at, updated_at"
)


def notice_detail(notice_id: int) -> dict | None:
    """单条详情 + 同项目时间线（供详情抽屉）。"""
    row = _rows(
        f"SELECT {FULL_NOTICE_SELECT} FROM notices WHERE id=%s",
        (notice_id,),
    )
    if not row:
        return None
    n = row[0]
    n["stage_label"] = STAGE_LABELS.get(n.get("notice_stage"), "其他")
    timeline: list[dict] = []
    if n.get("project_key"):
        timeline = _rows(
            "SELECT id, title, source_id, source_name, notice_stage, stage_rank, "
            "publish_date, detail_url, official_url, lead_status, read_at "
            "FROM notices WHERE project_key=%s ORDER BY stage_rank, publish_date, id",
            (n["project_key"],),
        )
    for t in timeline:
        t["stage_label"] = STAGE_LABELS.get(t.get("notice_stage"), "其他")
    return {"notice": n, "timeline": timeline}


def tenderfile_path_for(notice_id: int) -> str | None:
    """返回 tenderfile_path（相对项目根、正斜杠），无则 None。"""
    return _one("SELECT tenderfile_path AS p FROM notices WHERE id=%s", (notice_id,))


def export_csv(**filters) -> str:
    import csv
    import io

    wsql, args = _build_notices_where(
        filters.get("source_id"), filters.get("province"), filters.get("city"),
        filters.get("clean_status"), filters.get("only_pass"), filters.get("q"),
        filters.get("lead_status"), filters.get("amount_min"), filters.get("amount_max"),
        filters.get("target_only"), filters.get("stage"),
    )
    order = _SORTS.get(filters.get("sort"), _SORTS["created"])
    rows = _rows(f"SELECT {NOTICE_SELECT} FROM notices WHERE {wsql} ORDER BY {order} LIMIT 5000", tuple(args))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "标题", "源站", "城市", "省", "关键词", "阶段", "发布时间", "首次发现", "金额(元)", "金额文本",
                "招标人", "代理", "项目编号", "处理状态", "金额确认", "已读", "详情链接", "原文链接"])
    for r in rows:
        w.writerow([
            r.get("id"), r.get("title"), r.get("source_id"), r.get("city"), r.get("province"),
            r.get("keyword"), STAGE_LABELS.get(r.get("notice_stage"), "其他"),
            r.get("publish_date"), r.get("created_at"), r.get("amount"),
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
