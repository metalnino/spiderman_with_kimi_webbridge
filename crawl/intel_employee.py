"""实体情报员 · 员工外壳（implements: entity_intel/v1.0.0）

把采集员积累的公告（notices 表）升维成「实体情报图」，四层齐全：
  ① 身份层   IDENTITY / IMPLEMENTS = "entity_intel/v1.0.0"
  ② 契约层   校验契约 input，把聚合结果映射成 output schema（entities/winners/relations）
  ③ 配置层   复用 config/filters.json（地区白名单）+ config/crm_config.json（周期粗估阈值）
  ④ 观测层   每次运行写 reports/intel-report.json（7 项指标）

与采集员的关系：采集员产出「事件流」（单轮），实体情报员消费「积累的事件库」（跨轮、多年）
  产出「实体图」——采购人实体 + 中标企业（供给侧）+ 历史周期粗估 + 原发渠道 + 供需关系边。
  因此实体情报员的输入是 notices 累积库（DB），不是单轮 handoff；这是与解析员的关键区别。

红线自查：coreType=rule、autonomyBudget=deterministic；只做「抽取+聚合+粗估」，
  不做投标/分包任何业务决策；抽不到的中标企业如实 null（绝不编造）；周期粗估是提示非事实。
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from db import connect  # noqa: E402

from crawl import entity_aggregate as ea  # noqa: E402
from crawl import winner_extract as we  # noqa: E402

IMPLEMENTS = "entity_intel/v1.0.0"

IDENTITY = {
    "id": "entity_intel",
    "name": "实体情报员",
    "implements": IMPLEMENTS,
    "contractVersion": "1.0.0",
    "coreType": "rule",
    "autonomyBudget": "deterministic",
    "responsibility": "把累积公告升维成实体情报图：采购人实体聚合、中标企业抽取、历史周期粗估、原发渠道、供需关系",
    "output": "实体图 {entities, winners, relations} + 观测报告（周期粗估是提示非事实）",
}

# 契约 observability.metrics 的七个指标名
METRIC_NAMES = (
    "entity_count",
    "winner_count",
    "winner_extract_rate",
    "cycle_estimate_count",
    "official_channel_count",
    "notice_scanned",
    "elapsed_ms",
)

REPORT_PATH = ROOT / "reports" / "intel-report.json"
REPORT_HISTORY_DIR = ROOT / "reports" / "intel_history"


class ContractInputError(ValueError):
    """契约 input 校验失败（非业务错误，编排器可据此打回）。"""


# ---------------------------------------------------------------- 契约层：input ---

def validate_input(inp: dict | None) -> dict:
    """校验并规范化契约 input；inp=None 时退回默认（全量、无地区/时间过滤、抽取中标企业）。"""
    if inp is None:
        inp = {}
    if not isinstance(inp, dict):
        raise ContractInputError("input 必须是 JSON object")

    dr = inp.get("dateRange")
    dr_out = None
    if dr is not None:
        if not isinstance(dr, dict):
            raise ContractInputError("dateRange 必须是 {start, end} 对象")
        for k in ("start", "end"):
            if k in dr and dr[k] is not None and not isinstance(dr[k], str):
                raise ContractInputError(f"dateRange.{k} 必须是 ISO8601 字符串")
        dr_out = {"start": dr.get("start"), "end": dr.get("end")}

    rf = inp.get("regionFilter")
    if rf is not None and (not isinstance(rf, list) or not all(isinstance(x, str) for x in rf)):
        raise ContractInputError("regionFilter 必须是 string[]")
    rf_out = [str(x).strip() for x in rf if str(x).strip()] if rf else None

    plats = inp.get("platforms")
    if plats is not None and (not isinstance(plats, list) or not all(isinstance(x, str) for x in plats)):
        raise ContractInputError("platforms 必须是 string[]")
    plats_out = [str(x).strip() for x in plats if str(x).strip()] if plats else None

    extract_winners = inp.get("extractWinners", True)
    if not isinstance(extract_winners, bool):
        raise ContractInputError("extractWinners 必须是 bool")

    return {
        "dateRange": dr_out,
        "regionFilter": rf_out,
        "platforms": plats_out,
        "extractWinners": extract_winners,
    }


# ---------------------------------------------------------------- 内核 I/O（thin）---

def load_notices(norm: dict) -> list[dict]:
    """从 notices 累积库读公告（thin I/O）。过滤：非 drop、非 irrelevant、region、platforms、dateRange。"""
    where = [
        "(clean_status IS NULL OR clean_status <> 'drop')",
        "(manual_label IS NULL OR manual_label <> 'irrelevant')",
    ]
    args: list = []
    if norm["platforms"]:
        where.append("source_id IN (" + ",".join(["%s"] * len(norm["platforms"])) + ")")
        args.extend(norm["platforms"])
    if norm["regionFilter"]:
        city_cond = " OR ".join(["city=%s"] * len(norm["regionFilter"]))
        prov_cond = " OR ".join(["province=%s"] * len(norm["regionFilter"]))
        where.append(f"(({city_cond}) OR ({prov_cond}))")
        args.extend(norm["regionFilter"] * 2)
    if norm["dateRange"]:
        dr = norm["dateRange"]
        if dr.get("start"):
            where.append("publish_date >= %s")
            args.append(dr["start"])
        if dr.get("end"):
            where.append("publish_date <= %s")
            args.append(dr["end"])

    sql = (
        "SELECT id, source_id, title, city, province, publish_date, created_at, "
        "buyer, keyword, summary, notice_stage, stage_rank, project_key, project_name, "
        "original_url, origin_source, detail_url, official_url, winner "
        "FROM notices WHERE " + " AND ".join(where)
    )
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(args))
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def persist_winners(winners: list[dict]) -> int:
    """把抽取到的 winner 回写 notices.winner（thin I/O，幂等）。返回回写条数。"""
    n = 0
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            for w in winners:
                if w.get("noticeId") and w.get("name"):
                    cur.execute(
                        "UPDATE notices SET winner=%s WHERE id=%s",
                        (str(w["name"])[:256], w["noticeId"]),
                    )
                    n += 1
    finally:
        conn.close()
    return n


# ---------------------------------------------------------------- 纯函数（可测）---

def _iso(v) -> str | None:
    if not v:
        return None
    s = str(v).strip().replace(" ", "T")
    return s[:19]


def _winner_item(n: dict, name: str, source: str) -> dict:
    return {
        "name": name,
        "buyer": (n.get("buyer") or "").strip() or None,
        "projectName": n.get("project_name") or n.get("title"),
        "projectKey": n.get("project_key"),
        "noticeId": n.get("id"),
        "platform": n.get("source_id"),
        "url": n.get("detail_url") or n.get("official_url"),
        "wonAt": _iso(n.get("publish_date")),
        "extractSource": source,
    }


def extract_winners(notices: list[dict]) -> dict:
    """中标企业抽取：已有 winner 列（AI 兜底/历史）优先，result 阶段再确定性抽取。返回 {winners, stats}。"""
    winners: list[dict] = []
    seen_ids: set = set()
    result_total = 0
    extracted = 0
    for n in notices:
        nid = n.get("id")
        is_result = (n.get("notice_stage") or "").strip() == "result"
        if is_result:
            result_total += 1
        # 1) 已有 winner 列（ai_enrich / 上轮抽取写入）→ 直接纳入
        existing = (n.get("winner") or "").strip()
        if existing and nid not in seen_ids:
            seen_ids.add(nid)
            extracted += 1
            winners.append(_winner_item(n, existing, "db"))
            continue
        if not is_result:
            continue
        # 2) result 阶段无 winner → 确定性抽取
        r = we.extract_winner_from_notice(n)
        if r["status"] == "extracted" and nid not in seen_ids:
            seen_ids.add(nid)
            extracted += 1
            winners.append(_winner_item(n, r["winner"], r["source"]))
    rate = round(extracted / result_total, 3) if result_total else None
    return {"winners": winners, "stats": {"result_total": result_total, "extracted": extracted, "rate": rate}}


def build_relations(winners: list[dict]) -> list[dict]:
    """中标企业 → 采购人 供需关系边（闭环供给侧）。去重。"""
    seen: set = set()
    out: list[dict] = []
    for w in winners:
        if not w.get("buyer") or not w.get("name"):
            continue
        k = (w["buyer"], w["name"], w.get("projectKey") or "")
        if k in seen:
            continue
        seen.add(k)
        out.append({"buyer": w["buyer"], "winner": w["name"], "projectKey": w.get("projectKey")})
    return out


# ---------------------------------------------------------------- 主流程 ---

def run(inp: dict | None = None) -> dict:
    """契约 input → 契约 output + 观测报告。返回 {output, report, reportPath}。"""
    t0 = time.time()
    started = datetime.now()
    norm = validate_input(inp)

    notices = load_notices(norm)
    wres = extract_winners(notices)
    winners = wres["winners"]
    entities = ea.aggregate_entities(notices)
    relations = build_relations(winners)

    persisted = 0
    if norm["extractWinners"]:
        persisted = persist_winners(winners)

    metrics = {
        "entity_count": len(entities),
        "winner_count": len(winners),
        "winner_extract_rate": wres["stats"]["rate"],
        "cycle_estimate_count": sum(1 for e in entities if e["nextBidHint"]),
        "official_channel_count": sum(1 for e in entities if e["officialChannels"]),
        "notice_scanned": len(notices),
        "elapsed_ms": int((time.time() - t0) * 1000),
    }

    output = {"entities": entities, "winners": winners, "relations": relations}

    report = {
        "employee": IDENTITY["name"],
        "id": IDENTITY["id"],
        "implements": IMPLEMENTS,
        "contractVersion": IDENTITY["contractVersion"],
        "runId": started.strftime("intel-%Y%m%dT%H%M%S"),
        "startedAt": started.strftime("%Y-%m-%dT%H:%M:%S"),
        "finishedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "input": norm,
        "metrics": metrics,
        "winnerExtract": wres["stats"],
        "persistedWinners": persisted,
        "notes": [
            "winner_extract_rate 口径：成功抽取/结果公告数；无结果公告时为 null（不编 0）。抽不到（登录墙/无 summary/真流标）如实 unknown，winner 为 null。",
            "nextBidHint 是确定性规则的粗估提示，不是预测承诺；样本 < min_history_for_estimate 时为空，confidence 越低越不可靠。",
            "实体边界：采购人（buyer，需求侧客户）与中标企业（winner，供给侧/潜在分包商）是两类节点，relations 记录其供需关系边。",
            "本岗只「抽取+聚合+粗估」，不做投标/分包任何业务决策（红线）。",
        ],
    }

    report_path = Path(os.environ.get("SPIDER_INTEL_REPORT_PATH") or REPORT_PATH)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    try:
        REPORT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        hist = REPORT_HISTORY_DIR / f"{report['runId']}.json"
        i = 1
        while hist.exists():
            i += 1
            hist = REPORT_HISTORY_DIR / f"{report['runId']}-{i}.json"
        hist.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # 归档失败不影响本轮主报告与产出

    return {"output": output, "report": report, "reportPath": str(report_path)}
