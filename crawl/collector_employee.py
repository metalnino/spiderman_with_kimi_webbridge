"""招标采集员 · 员工外壳（implements: collector/v1.0.0）

本模块是「内核 + 外壳」里的外壳（适配层），四层齐全：
  ① 身份层   IDENTITY / IMPLEMENTS = "collector/v1.0.0"
  ② 契约层   校验契约 input，把内核 Notice 映射成契约 output schema
             （title/platform/url/publishTime/region/amount/summary/dedupId）
  ③ 配置层   config/keywords.json | config/platforms.json | config/filters.json（改进层可改、git 可回滚）
  ④ 观测层   每次运行写 reports/collector-report.json，指标严格对齐契约 observability.metrics

内核 = 各平台已攻克的执行路径，原样调用、不重写：
  - HTTP 平台（ccgp/chinabidding/ggzy/jsggzy）→ crawl.runner.run_source（内核原路径）
  - cebpub → scripts/crawl_cebpub_pw.main（Playwright 无头，performSearchRequest 路径）
  - jiangsu_zhaobiao → scripts/crawl_jiangsu_wb.main（WebBridge 真浏览器，JSL 两阶段路径）
路由表见 BROWSER_ROUTES（与 config/platforms.json 的 route 字段一致）。

红线自查：coreType=rule、autonomyBudget=deterministic；不做报价/关系/投标任何业务决策。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from db import connect  # noqa: E402

from crawl import runner  # noqa: E402
from crawl.models import Notice  # noqa: E402
from crawl.sources import REGISTRY as SOURCE_REGISTRY  # noqa: E402

IMPLEMENTS = "collector/v1.0.0"

IDENTITY = {
    "id": "collector",
    "name": "招标采集员",
    "implements": IMPLEMENTS,
    "contractVersion": "1.0.0",
    "coreType": "rule",
    "autonomyBudget": "deterministic",
    "responsibility": "从各招标平台抓取绿植租摆公告并去重",
    "output": "结构化公告条目数组",
}

# 契约 output.items 的字段清单（顺序即输出顺序）
OUTPUT_KEYS = ("title", "platform", "url", "publishTime", "region", "amount", "summary", "dedupId")

# 契约 observability.metrics 的六个指标名（报告 metrics 对象必须恰好覆盖）
METRIC_NAMES = (
    "fetched_count",
    "dedup_new_count",
    "platform_success_rate",
    "empty_platforms",
    "blocked_count",
    "elapsed_ms",
)

REPORT_PATH = ROOT / "reports" / "collector-report.json"

_BLOCK_MARKERS = ("http 403", "rate_limited", "频繁", "频控", "封禁", "blocked")

# 平台 → 非 HTTP 执行路径（与 config/platforms.json 的 route 字段一致）
BROWSER_ROUTES = {
    "cebpub": {"route": "playwright", "module": "crawl_cebpub_pw"},
    "jiangsu_zhaobiao": {"route": "webbridge", "module": "crawl_jiangsu_wb"},
}


def _run_platform(pid: str, keywords: list[str], max_pages: int) -> dict:
    """平台→执行路径路由。统一返回 {status, error, notices:[dict], raw_total, run_id}。"""
    route = BROWSER_ROUTES.get(pid)
    if not route:
        return runner.run_source(pid, keywords=keywords, max_pages=max_pages)
    if route["route"] == "webbridge":
        # 一键开桥（幂等）：桥服务/浏览器/扩展三件套自动就位，不再依赖人工打开
        from crawl import webbridge_client as wb

        try:
            wb.ensure_bridge()
        except Exception as e:  # noqa: BLE001 —— 开桥失败不炸整轮，由下游如实报 not_available
            print(f"[collector] webbridge ensure_bridge failed: {e}", flush=True)
    import importlib

    try:
        res = importlib.import_module(route["module"]).main(keywords) or {}
    except Exception as e:  # noqa: BLE001 —— 浏览器路径异常也要闭环上报
        return {"status": "error", "error": str(e)[:300], "notices": [], "raw_total": None, "run_id": None}
    return {
        "status": res.get("status") or "error",
        "error": res.get("error"),
        "notices": list(res.get("notices") or []),
        "raw_total": None,
        "run_id": None,
    }


class ContractInputError(ValueError):
    """契约 input 校验失败（非业务错误，编排器可据此打回）。"""


# ---------------------------------------------------------------- 配置层 ---

def load_keywords() -> list[str]:
    p = ROOT / "config" / "keywords.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [str(k).strip() for k in data if str(k).strip()]


def load_platforms() -> list[dict]:
    p = ROOT / "config" / "platforms.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [e for e in (data or []) if isinstance(e, dict) and e.get("id")]


def load_filters() -> dict:
    p = ROOT / "config" / "filters.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------- 契约层：input ---

def validate_input(inp: Optional[dict]) -> dict:
    """校验并规范化契约 input；inp=None 时退回配置层默认（人工直跑入口用）。"""
    use_config_defaults = inp is None
    if inp is None:
        inp = {}
    if not isinstance(inp, dict):
        raise ContractInputError("input 必须是 JSON object")

    kws = inp.get("keywords")
    if kws is None:
        if use_config_defaults:
            kws = load_keywords()
            if not kws:
                raise ContractInputError("keywords 缺失：契约必填 string[]，且 config/keywords.json 为空")
        else:
            raise ContractInputError("keywords 缺失：契约必填 string[]")
    if not isinstance(kws, list) or not kws or not all(isinstance(k, str) and k.strip() for k in kws):
        raise ContractInputError("keywords 必须是 string[] 且非空")
    kws = [str(k).strip() for k in kws]

    plats = inp.get("platforms")
    if plats is None:
        if use_config_defaults:
            plats = [p["id"] for p in load_platforms() if p.get("enabled") is not False]
            if not plats:
                raise ContractInputError("platforms 缺失：契约必填 string[]，且 config/platforms.json 无启用平台")
        else:
            raise ContractInputError("platforms 缺失：契约必填 string[]")
    if not isinstance(plats, list) or not plats or not all(isinstance(x, str) and x.strip() for x in plats):
        raise ContractInputError("platforms 必须是 string[] 且非空")
    plats = [str(x).strip() for x in plats]

    dr = inp.get("dateRange")
    if dr is not None:
        if not isinstance(dr, dict):
            raise ContractInputError("dateRange 必须是 {start, end} 对象")
        for k in ("start", "end"):
            if k in dr and dr[k] is not None and not isinstance(dr[k], str):
                raise ContractInputError(f"dateRange.{k} 必须是 ISO8601 字符串")
    dr_out = None
    if dr:
        dr_out = {"start": dr.get("start"), "end": dr.get("end")}

    rf = inp.get("regionFilter")
    if rf is not None and (not isinstance(rf, list) or not all(isinstance(x, str) for x in rf)):
        raise ContractInputError("regionFilter 必须是 string[]")
    rf_out = [str(x).strip() for x in rf if str(x).strip()] if rf else None

    return {"keywords": kws, "platforms": plats, "dateRange": dr_out, "regionFilter": rf_out}


def resolve_platforms(plats: list[str]) -> tuple[list[str], list[dict]]:
    """平台清单 → (本轮要跑的, 跳过项)。跳过原因显式上报，不静默。"""
    cfg = {p["id"]: p for p in load_platforms()}
    run_list: list[str] = []
    skipped: list[dict] = []
    for pid in plats:
        if pid not in SOURCE_REGISTRY:
            skipped.append({"platform": pid, "reason": "unknown_platform"})
            continue
        if (cfg.get(pid) or {}).get("enabled") is False:
            skipped.append({"platform": pid, "reason": "disabled_in_platforms_config"})
            continue
        run_list.append(pid)
    return run_list, skipped


def default_date_since_last_run() -> Optional[dict]:
    """契约 input.dateRange 缺省语义：上次运行点至今。"""
    try:
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(finished_at) AS t FROM crawl_runs WHERE finished_at IS NOT NULL")
                row = cur.fetchone()
        finally:
            conn.close()
        if row and row.get("t"):
            return {"start": str(row["t"])[:19].replace(" ", "T"), "end": None}
    except Exception:
        pass
    return None


def effective_filters(inp: dict, filters: dict) -> dict:
    """过滤条件解析。优先级：契约 input > config/filters.json > 契约缺省。"""
    f = filters or {}
    region = inp.get("regionFilter")
    if region is None:
        rg = f.get("region") or {}
        if rg.get("enabled"):
            region = [str(c).strip() for c in (rg.get("cities") or []) if str(c).strip()]
    date = inp.get("dateRange")
    if date is None:
        d = f.get("date") or {}
        if d.get("enabled") and (d.get("start") or d.get("end")):
            date = {"start": d.get("start"), "end": d.get("end")}
    if date is None:
        date = default_date_since_last_run()
    budget = None
    b = f.get("budget") or {}
    if b.get("enabled") and (b.get("min_yuan") is not None or b.get("max_yuan") is not None):
        budget = {"min_yuan": b.get("min_yuan"), "max_yuan": b.get("max_yuan")}
    return {"region": region or None, "date": date, "budget": budget}


# ---------------------------------------------------------------- 纯函数（契约测试可直接覆盖） ---

def _g(n, key, default=None):
    """Notice 对象与 JSON dict 双形态取值（内核返回 JSON 安全 dict，单测可传 Notice）。"""
    if isinstance(n, dict):
        return n.get(key, default)
    return getattr(n, key, default)


def _to_iso8601(v) -> str:
    if not v:
        return ""
    s = str(v).strip().replace(" ", "T")
    return s[:19]


def to_contract_item(n) -> dict:
    """内核 Notice（或等价 dict）→ 契约 output.items。dedupId = md5(title+platform+url)（契约口径）。"""
    title = (_g(n, "title") or "").strip()
    platform = (_g(n, "source_id") or "").strip()
    url = (_g(n, "detail_url") or _g(n, "official_url") or "").strip()
    publishTime = _to_iso8601(_g(n, "publish_date"))
    region = (_g(n, "city") or _g(n, "province") or _g(n, "region_text") or "").strip()
    amount_text = _g(n, "amount_text")
    amount = str(amount_text).strip() if amount_text else None
    summary = None  # 契约允许 nullable；内核暂无正文摘要能力，不造假
    dedupId = hashlib.md5((title + platform + url).encode("utf-8")).hexdigest()
    return {
        "title": title,
        "platform": platform,
        "url": url,
        "publishTime": publishTime,
        "region": region,
        "amount": amount,
        "summary": summary,
        "dedupId": dedupId,
    }


def dedup_items(items: list[dict]) -> list[dict]:
    """按 dedupId 去重（契约：输出去重后的数组）。保留先到者，顺序稳定。"""
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        k = it.get("dedupId") or ""
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def _in_date(pub: str, dr: Optional[dict]) -> bool:
    if not dr or (not dr.get("start") and not dr.get("end")):
        return True
    if not pub:
        return True  # 无日期不因范围丢弃（与内核 _in_pub_range 口径一致）
    d = str(pub)[:10]
    if dr.get("start") and d < dr["start"]:
        return False
    if dr.get("end") and d > dr["end"]:
        return False
    return True


def _in_region(region: str, whitelist: list[str]) -> bool:
    return any(c in region for c in whitelist)


def count_blocked_events(errors: list) -> int:
    """403/频控/封禁 事件数。口径：源站最终错误串中的封禁信号；内核重试期的内部 403 不对外可见。"""
    total = 0
    for err in errors or []:
        if not err:
            continue
        n = 0
        low = str(err).lower()
        for m in _BLOCK_MARKERS:
            n += len(re.findall(re.escape(m), low))
        hit = re.search(r"连续\s*(\d+)\s*次", str(err))
        if hit:
            n = max(n, int(hit.group(1)))
        total += n
    return total


# ---------------------------------------------------------------- 内核调用 ---

def _existing_hashes(pid: str) -> set[str]:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT content_hash FROM notices WHERE source_id=%s", (pid,))
            return {r["content_hash"] for r in cur.fetchall()}
    finally:
        conn.close()


# ---------------------------------------------------------------- 主流程 ---

def run(inp: Optional[dict] = None, *, max_pages: Optional[int] = None) -> dict:
    """契约 input → 契约 output + 观测报告。

    返回 {"output": [...], "report": {...}, "reportPath": str}。
    观测报告每次运行覆写 reports/collector-report.json（契约 reportPath）。
    """
    t0 = time.time()
    started = datetime.now()
    norm = validate_input(inp)
    filters = effective_filters(norm, load_filters())
    run_list, skipped = resolve_platforms(norm["platforms"])
    if max_pages is None:
        env = os.environ.get("SPIDER_MAX_PAGES")
        max_pages = int(env) if env and str(env).isdigit() else 1

    per_platform: list[dict] = []
    errors_by_platform: list = []
    fetched_total = 0
    dedup_new_total = 0
    success_rate: dict[str, float] = {}
    empty_platforms: list[str] = []
    collected: list = []

    for pid in run_list:
        existing = _existing_hashes(pid)
        try:
            res = _run_platform(pid, norm["keywords"], max_pages)
        except Exception as e:  # noqa: BLE001 —— 内核意外失败也要闭环上报，不能炸掉整轮
            res = {
                "source_id": pid, "run_id": None, "status": "error",
                "error": str(e)[:300], "notices": [], "raw_total": 0, "attempted": 0,
            }
        notices = list(res.get("notices") or [])
        err = res.get("error")
        errors_by_platform.append(err)
        fetched = len(notices)
        fetched_total += fetched
        new_hashes = 0
        for n in notices:
            h = n.get("content_hash") if isinstance(n, dict) else n.content_hash()
            if h not in existing:
                new_hashes += 1
                existing.add(h)
        dedup_new_total += new_hashes
        status = str(res.get("status") or "error")
        success_rate[pid] = 0.0 if status in ("failed", "error") else 1.0
        if fetched == 0:
            empty_platforms.append(pid)
        per_platform.append({
            "platform": pid,
            "status": status,
            "fetched": fetched,
            "dedup_new": new_hashes,
            "raw_total": res.get("raw_total"),
            "kernel_run_id": res.get("run_id"),
            "error": err,
        })
        collected.extend(notices)

    # 外壳过滤 + 契约输出映射（input > filters.json 已在上层解析）
    drop_counts = {"date": 0, "region": 0, "budget": 0}
    out_raw: list[dict] = []
    for n in collected:
        pub = str(_g(n, "publish_date") or "")[:10]
        if not _in_date(pub, filters["date"]):
            drop_counts["date"] += 1
            continue
        region = (_g(n, "city") or _g(n, "province") or _g(n, "region_text") or "").strip()
        if filters["region"] and not _in_region(region, filters["region"]):
            drop_counts["region"] += 1
            continue
        amount = _g(n, "amount")
        if filters["budget"] and amount is not None:
            lo, hi = filters["budget"].get("min_yuan"), filters["budget"].get("max_yuan")
            if (lo is not None and amount < lo) or (hi is not None and amount > hi):
                drop_counts["budget"] += 1
                continue
        out_raw.append(to_contract_item(n))
    output = dedup_items(out_raw)

    # 观测指标（严格对齐契约 observability.metrics 六项）
    metrics = {
        "fetched_count": fetched_total,
        "dedup_new_count": dedup_new_total,
        "platform_success_rate": success_rate,
        "empty_platforms": empty_platforms,
        "blocked_count": count_blocked_events(errors_by_platform),
        "elapsed_ms": int((time.time() - t0) * 1000),
    }

    report = {
        "employee": IDENTITY["name"],
        "id": IDENTITY["id"],
        "implements": IMPLEMENTS,
        "contractVersion": IDENTITY["contractVersion"],
        "runId": started.strftime("collector-%Y%m%dT%H%M%S"),
        "startedAt": started.strftime("%Y-%m-%dT%H:%M:%S"),
        "finishedAt": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "input": norm,
        "effectiveFilters": {k: v for k, v in filters.items() if v},
        "metrics": metrics,
        "perPlatform": per_platform,
        "skipped": skipped,
        "filterDrops": drop_counts,
        "missingPublishTimeCount": sum(1 for it in output if not it["publishTime"]),
        "notes": [
            "blocked_count 口径：源站最终错误串中的 403/频控/封禁 信号数（内核内部重试期间的 403 不对外可见）。",
            "platform_success_rate 口径：1.0=success/partial，0.0=failed/error；失败且 0 结果同时进入 empty_platforms。",
            "publishTime 缺失时输出空串（契约该字段非 nullable；内核源站偶无日期，不改契约、不造假，见交付报告）。",
        ],
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"output": output, "report": report, "reportPath": str(REPORT_PATH)}
