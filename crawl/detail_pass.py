"""详情正文补全（有界、配置驱动）—— 采集轮内与手动入口共用的一份实现。

为什么需要它（2026-09-19 实测：3166 条公告里 detail_status 为 null 的 3103 条、
真正落到附件正文 tenderfile_path 的只有 7 条）：瓶颈**不是反爬**，而是这条链从来没被调度 ——
  - 轮内 `crawl.detail.enrich_source_details` 只做金额等**字段级**回填，且以 `amount IS NULL` 为条件；
  - `crawl.backfill.auto_backfill_pass` 只碰 ccgp/ggzy/jsggzy，且仅限「可投标阶段 + 缺金额」；
  - 唯一调用完整链（详情 → 原发寻址 → 原发转爬 + AI 兜底）的 `scripts/collector_detail.py`
    没有接进任何定时任务（本机无权新建计划任务：`Register-ScheduledTask` 需提权）。
结果：下游「解析员 → 资格评估 → 标书撰写」整条链拿不到招标文件正文。

本模块把这条链做成**一个有界阶段**，由采集轮直接调用，于是它每轮都会真的跑：
  - 候选有优先级（可投标阶段优先，其次发布时间新→旧）；
  - 单轮总数 / 每站条数 / 总耗时三重封顶（jiangsu 单条实测可达 91s，必须限时）；
  - 一次一条、失败如实落 `detail_status=err:<原因>` 不轰炸；
  - AI 兜底默认关（控成本与时延），`SPIDER_DETAIL_AI=1` 或配置打开。

候选口径：`detail_status` 为空（从没试过）或**可自愈的瞬时失败**（桥掉线 / 详情页抓取失败），
且 summary 仍不够长。永久性失败（验证码门 / 登录墙 / 无附件链接）不重复尝试。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from db import connect  # noqa: E402

# 可投标阶段优先（投标中 > 意向 > 变更 > 候选人 > 结果 > 开标 > 预审 > 其他 > 终止）
STAGE_ORDER_SQL = """
  CASE notice_stage
    WHEN 'bidding' THEN 1
    WHEN 'intent' THEN 2
    WHEN 'change' THEN 3
    WHEN 'candidate' THEN 4
    WHEN 'result' THEN 5
    WHEN 'opening' THEN 6
    WHEN 'preselect' THEN 7
    WHEN 'other' THEN 8
    ELSE 9
  END
"""

DEFAULT_CFG: dict = {
    "enabled": True,
    "limit_total": 40,
    "per_source_limit": 6,
    "max_seconds": 600,
    "min_summary_chars": 400,
    "use_ai": False,
    # cebpub 详情需人工过一次 vaptcha（每条 15~20s 且必失败），默认排除；rccchina 注册墙同理
    "exclude_sources": ["cebpub", "rccchina"],
    # 只重试「可自愈」的失败，永久性失败（验证码门/登录墙/无附件）不重复打
    "retry_error_prefixes": ["err:bridge", "err:detail_page", "err:fetch"],
}


def load_cfg() -> dict:
    """读 config/anti_bot.json 的 detail_pass 块，缺项用默认值补齐。"""
    cfg = dict(DEFAULT_CFG)
    try:
        from crawl.config_loader import anti_bot_cfg

        blk = (anti_bot_cfg() or {}).get("detail_pass") or {}
        if isinstance(blk, dict):
            cfg.update({k: v for k, v in blk.items() if not str(k).startswith("$")})
    except Exception:  # noqa: BLE001 —— 配置读不到就用默认，绝不挡采集
        pass
    if os.environ.get("SPIDER_NO_DETAIL_PASS"):
        cfg["enabled"] = False
    if os.environ.get("SPIDER_DETAIL_AI"):
        cfg["use_ai"] = True
    for env_key, cfg_key, cast in (
        ("SPIDER_DETAIL_PASS_TOTAL", "limit_total", int),
        ("SPIDER_DETAIL_PASS_PER_SOURCE", "per_source_limit", int),
        ("SPIDER_DETAIL_PASS_MAX_SEC", "max_seconds", int),
    ):
        raw = os.environ.get(env_key)
        if raw and str(raw).lstrip("-").isdigit():
            cfg[cfg_key] = cast(raw)
    return cfg


def pick_candidates(*, limit_total: int, per_source_limit: int, min_summary_chars: int,
                    exclude_sources=(), sources=None, retry_error_prefixes=()) -> list[dict]:
    """按优先级取候选（多取留 per-source 截断余量）。失败返回空列表，绝不抛。"""
    pool = int(max(limit_total, 1) * 4)
    where = [
        "detail_url IS NOT NULL",
        "detail_url <> ''",
    ]
    params: list = []
    status_bits = ["detail_status IS NULL"]
    for pref in retry_error_prefixes:
        status_bits.append("detail_status LIKE %s")
        params.append(pref + "%")
    where.append("(" + " OR ".join(status_bits) + ")")
    where.append("(summary IS NULL OR CHAR_LENGTH(summary) < %s)")
    params.append(int(min_summary_chars))
    if sources:
        marks = ",".join(["%s"] * len(sources))
        where.append(f"source_id IN ({marks})")
        params.extend(list(sources))
    if exclude_sources:
        marks = ",".join(["%s"] * len(exclude_sources))
        where.append(f"source_id NOT IN ({marks})")
        params.extend(list(exclude_sources))
    sql = (
        "SELECT id, source_id, title, detail_url, notice_stage, publish_date FROM notices WHERE "
        + " AND ".join(where)
        + " ORDER BY "
        + STAGE_ORDER_SQL
        + ", publish_date DESC, id DESC LIMIT %s"
    )
    params.append(pool)
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def run_detail_pass(
    *,
    limit_total: int = 40,
    per_source_limit: int = 6,
    max_seconds: int = 600,
    min_summary_chars: int = 400,
    use_ai: bool = False,
    exclude_sources=(),
    sources=None,
    retry_error_prefixes=(),
    candidates_fn=None,
    backfill_fn=None,
    ai_fn=None,
    log=lambda msg: None,
) -> dict:
    """跑一轮有界详情补全。返回统计（含每条 traces，供自评与调试）。

    candidates_fn / backfill_fn / ai_fn 可注入（手动入口与单测用）；缺省走真实实现。
    """
    from crawl.backfill import ai_enrich_notice, backfill_notice

    backfill_fn = backfill_fn or backfill_notice
    ai_fn = ai_fn or ai_enrich_notice

    stats: dict = {
        "enabled": True,
        "use_ai": bool(use_ai),
        "candidates": 0,
        "processed": 0,
        "detail_ok": 0,
        "text_ok": 0,          # 真正拿到附件正文（下游解析员最需要的）
        "summary_ok": 0,       # 拿到摘要（正文）
        "ai_ok": 0,
        "ai_failed": 0,
        "failed": 0,
        "stopped_reason": None,
        "elapsed_ms": 0,
        "per_source": {},
        "errors": [],
        "traces": [],
    }
    t0 = time.time()
    if candidates_fn is not None:
        cands = list(candidates_fn() or [])
    else:
        cands = pick_candidates(
            limit_total=limit_total,
            per_source_limit=per_source_limit,
            min_summary_chars=min_summary_chars,
            exclude_sources=exclude_sources,
            sources=sources,
            retry_error_prefixes=retry_error_prefixes,
        )
    stats["candidates"] = len(cands)
    deadline = (t0 + max_seconds) if max_seconds and max_seconds > 0 else None
    done = 0
    for c in cands:
        if done >= limit_total:
            stats["stopped_reason"] = "limit_total"
            break
        if deadline and time.time() >= deadline:
            stats["stopped_reason"] = "time_budget"
            log(f"[detail-pass] 时间预算 {max_seconds}s 用尽，余下候选留待下轮")
            break
        sid = c.get("source_id") or "?"
        per = stats["per_source"].setdefault(
            sid, {"attempted": 0, "detail_ok": 0, "text_ok": 0, "ai_ok": 0}
        )
        if per["attempted"] >= per_source_limit:
            continue
        nid = c.get("id")
        per["attempted"] += 1
        done += 1
        trace: dict = {"id": nid, "source_id": sid, "title": (c.get("title") or "")[:40]}
        try:
            r = backfill_fn(nid) or {}
        except Exception as e:  # noqa: BLE001
            r = {"ok": False, "error": f"{type(e).__name__}:{e}"[:120]}
        got_text = bool(r.get("tenderfile_path"))
        summary = r.get("summary") or ""
        trace["detail"] = {
            "ok": bool(r.get("ok")),
            "error": r.get("error"),
            "origin_url": r.get("original_url"),
            "origin_source": r.get("origin_source"),
            "origin_fetched": bool(r.get("origin_fetched")),
            "summary_chars": len(summary) if isinstance(summary, str) else 0,
            "tenderfile": r.get("tenderfile_path"),
        }
        if r.get("ok"):
            stats["detail_ok"] += 1
            per["detail_ok"] += 1
        else:
            stats["failed"] += 1
            if len(stats["errors"]) < 20:
                stats["errors"].append({"id": nid, "source_id": sid, "error": r.get("error")})
        if got_text:
            stats["text_ok"] += 1
            per["text_ok"] += 1
        if isinstance(summary, str) and len(summary) >= min_summary_chars:
            stats["summary_ok"] += 1
        if use_ai:
            try:
                a = ai_fn(nid) or {}
            except Exception as e:  # noqa: BLE001
                a = {"ok": False, "error": f"{type(e).__name__}:{e}"[:120]}
            trace["ai"] = {"ok": bool(a.get("ok")), "filled": a.get("filled"), "error": a.get("error")}
            if a.get("ok"):
                stats["ai_ok"] += 1
                per["ai_ok"] += 1
            else:
                stats["ai_failed"] += 1
        stats["traces"].append(trace)
        log(
            f"[detail-pass] {sid} #{nid} ok={bool(r.get('ok'))} "
            f"summary={trace['detail']['summary_chars']}字 text={'Y' if got_text else 'N'} "
            f"err={r.get('error') or '-'}"
        )
    stats["processed"] = done
    if stats["stopped_reason"] is None:
        # 候选跑完（含被 per-source 截断后无剩余）——与「撞上限/撞时限」区分开，便于看台账判断
        stats["stopped_reason"] = "candidates_exhausted"
    stats["elapsed_ms"] = int((time.time() - t0) * 1000)
    return stats
