from __future__ import annotations

import os
import time
from dataclasses import asdict

from crawl.captcha_queue import open_todo
from crawl.config_loader import anti_bot_cfg, only_target_cities, publish_date_range, sources_cfg, target_city_names
from crawl.db_store import finish_run, start_run, upsert_notices
from crawl.keywords import enabled_keywords
from crawl.pipeline.apply_clean import refresh_clean_status
from crawl.detail import enrich_source_details
from crawl.sources import enabled_source_ids, get_source
from crawl.sources.base import SourceError
from crawl.warm_session import warm_source


def _max_keywords_per_run() -> int:
    """每站每轮最多爬几个词；0=不限（默认）。SPIDER_MAX_KEYWORDS 或 anti_bot.http.max_keywords_per_run 覆盖。"""
    v = os.environ.get("SPIDER_MAX_KEYWORDS")
    if v:
        try:
            return max(0, int(v))
        except ValueError:
            pass
    ab = anti_bot_cfg()
    return int(((ab.get("http") or {}).get("max_keywords_per_run")) or 0)


def _in_pub_range(pub, pmin: str | None, pmax: str | None) -> bool:
    if not pub:
        return True  # 无日期不因范围丢弃
    d = str(pub)[:10]
    if pmin and d < pmin:
        return False
    if pmax and d > pmax:
        return False
    return True


def _max_detail_per_run() -> int:
    """每站每轮最多回填几条详情；0=关闭。SPIDER_MAX_DETAIL 覆盖。"""
    v = os.environ.get("SPIDER_MAX_DETAIL")
    if v:
        try:
            return max(0, int(v))
        except ValueError:
            pass
    return 5


def _collect(src, kws: list[str], max_pages: int) -> tuple[list, str | None]:
    """采集并保留部分结果：SourceError.partial 必须入库而不是丢弃。"""
    try:
        return list(src.fetch(kws, max_pages=max_pages)), None
    except SourceError as e:
        return e.partial, str(e)
    except Exception as e:  # noqa: BLE001
        return [], str(e) or type(e).__name__


def _is_rate_limited(err: str | None) -> bool:
    return bool(err) and any(k in (err or "").lower() for k in ("rate_limited", "429", "频控", "频繁"))


def _rate_limit_retry_cfg(source_id: str) -> tuple[bool, int]:
    """频控后是否冷却整站重试一次 + 冷却秒数（环境变量可覆盖，便于测试）。"""
    per = (anti_bot_cfg().get("per_source") or {}).get(source_id) or {}
    env = os.environ.get("SPIDER_RATE_LIMIT_COOLDOWN_SEC")
    cooldown = int(env) if env and str(env).isdigit() else int(per.get("rate_limit_cooldown_sec") or 300)
    enabled = bool(per.get("rate_limit_retry_once")) and "SPIDER_NO_RATE_LIMIT_RETRY" not in os.environ
    return enabled, cooldown


def run_source(source_id: str, *, keywords: list[str] | None = None, max_pages: int = 1) -> dict:
    kws = keywords or enabled_keywords()
    limit = _max_keywords_per_run()
    if limit and len(kws) > limit:
        kws = kws[:limit]
    src = get_source(source_id)
    warm_info = warm_source(source_id, src.http)
    run_id = start_run(source_id)
    notices, err = _collect(src, kws, max_pages)
    # 频控兜底：冷却后整站自动重试一次（结果合并，upsert 幂等，不丢已采部分）
    if err and _is_rate_limited(err):
        enabled, cooldown = _rate_limit_retry_cfg(source_id)
        if enabled:
            print(f"[run] {source_id} 频控命中，冷却 {cooldown}s 后自动重试一次", flush=True)
            time.sleep(cooldown)
            more, err2 = _collect(get_source(source_id), kws, max_pages)
            notices.extend(more)
            err = err2 if not more else (err2 or None)
            print(f"[run] {source_id} 频控重试: +{len(more)} 条, err={err2}", flush=True)
    raw_total = len(notices)
    # P7 召回自证：水位合并用「原始已见」id（含后续被城市/日期过滤丢弃的），
    # 下一轮才能越过已见页继续深扫；同时给出 wm_new/wm_total 让 0 新增可自证。
    from crawl import watermark as wm_mod

    wm_new, wm_total = wm_mod.merge(source_id, [n.external_id for n in notices if n.external_id])
    scanned_pages = getattr(src, "last_scanned_pages", None)
    if scanned_pages is not None:
        wm_mod.set_last_pages(source_id, max(wm_mod.get_last_pages(source_id) or 0, scanned_pages))
    if only_target_cities():
        targets = set(target_city_names())
        notices = [n for n in notices if (n.city or "") in targets]
    city_drop = raw_total - len(notices)
    pmin, pmax = publish_date_range()
    if pmin or pmax:
        notices = [n for n in notices if _in_pub_range(n.publish_date, pmin, pmax)]
    date_drop = raw_total - city_drop - len(notices)
    stats = upsert_notices(notices)
    clean_stats = refresh_clean_status(limit=max(200, stats["attempted"] * 3))
    detail_stats = enrich_source_details(source_id, limit=_max_detail_per_run())
    # cebpub 详情验证码：为样本登记待办（不阻塞列表）
    if source_id == "cebpub":
        for n in notices[:3]:
            if n.detail_url:
                open_todo(source_id, n.detail_url, n.title, note="detail_may_need_captcha")
    status = "success" if not err else ("partial" if stats["attempted"] else "failed")
    note = (
        f"raw={raw_total} city_drop={city_drop} date_drop={date_drop} "
        f"upsert≈{stats['affected']} clean={clean_stats} detail={detail_stats} "
        f"wm_new={wm_new} wm_total={wm_total} pages={scanned_pages} "
        f"warm={warm_info.get('warmed')} kw={kws} err={err or ''}"
    )[:500]
    if err and ("captcha" in err.lower() or "rate_limited" in err.lower() or "829" in err):
        open_todo(source_id, f"source://{source_id}", title=source_id, note=err[:200])
    finish_run(run_id, status=status, item_count=stats["attempted"], note=note)
    # 外壳适配层（collector/v1.0.0）用：原始采集数 + 过滤后入库的公告列表。
    # 纯增量返回字段，不改动内核任何控制流；notices 为 JSON 安全 dict（含 content_hash）。
    notice_dicts = [{**asdict(n), "content_hash": n.content_hash()} for n in notices]
    return {
        "source_id": source_id,
        "run_id": run_id,
        "status": status,
        "keywords": kws,
        "clean": clean_stats,
        "detail": detail_stats,
        "warm": warm_info,
        "watermark": {"new": wm_new, "total": wm_total, "pages": scanned_pages},
        "error": err,
        "raw_total": raw_total,
        "notices": notice_dicts,
        **stats,
    }


def run_incremental(*, sources: list[str] | None = None, max_pages: int = 1) -> list[dict]:
    cfg = sources_cfg()
    order = sources or enabled_source_ids()
    results = []
    for sid in order:
        sc = cfg.get(sid) or {}
        if sc.get("enabled") is False:
            results.append({"source_id": sid, "status": "skipped", "note": "disabled"})
            continue
        print(f"[run] {sid} ...", flush=True)
        r = run_source(sid, max_pages=max_pages)
        print(f"[run] {sid} -> {r.get('status')} attempted={r.get('attempted')} err={r.get('error')}", flush=True)
        results.append(r)
    return results


def run_sources_parallel(
    sources: list[str],
    *,
    keywords: list[str],
    max_pages: int = 1,
    max_workers: int = 4,
) -> dict:
    """并行跑多个源站（线程池，I/O 密集）。返回 {source_id: result}。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: dict = {}
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(run_source, sid, keywords=keywords, max_pages=max_pages): sid for sid in sources}
        for fut in as_completed(futs):
            sid = futs[fut]
            try:
                results[sid] = fut.result()
            except Exception as e:  # noqa: BLE001
                results[sid] = {"source_id": sid, "status": "error", "error": str(e)[:300]}
    return results
