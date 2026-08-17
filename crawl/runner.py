from __future__ import annotations

import os

from crawl.captcha_queue import open_todo
from crawl.config_loader import anti_bot_cfg, only_target_cities, publish_date_range, sources_cfg, target_city_names
from crawl.db_store import finish_run, start_run, upsert_notices
from crawl.keywords import enabled_keywords
from crawl.pipeline.apply_clean import refresh_clean_status
from crawl.detail import enrich_source_details
from crawl.sources import enabled_source_ids, get_source
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


def run_source(source_id: str, *, keywords: list[str] | None = None, max_pages: int = 1) -> dict:
    kws = keywords or enabled_keywords()
    limit = _max_keywords_per_run()
    if limit and len(kws) > limit:
        kws = kws[:limit]
    src = get_source(source_id)
    warm_info = warm_source(source_id, src.http)
    run_id = start_run(source_id)
    try:
        notices = list(src.fetch(kws, max_pages=max_pages))
        if only_target_cities():
            targets = set(target_city_names())
            notices = [n for n in notices if (n.city or "") in targets]
        pmin, pmax = publish_date_range()
        if pmin or pmax:
            notices = [n for n in notices if _in_pub_range(n.publish_date, pmin, pmax)]
        stats = upsert_notices(notices)
        clean_stats = refresh_clean_status(limit=max(200, stats["attempted"] * 3))
        detail_stats = enrich_source_details(source_id, limit=_max_detail_per_run())
        # cebpub 详情验证码：为样本登记待办（不阻塞列表）
        if source_id == "cebpub":
            for n in notices[:3]:
                if n.detail_url:
                    open_todo(source_id, n.detail_url, n.title, note="detail_may_need_captcha")
        finish_run(
            run_id,
            status="success",
            item_count=stats["attempted"],
            note=f"upsert≈{stats['affected']} clean={clean_stats} detail={detail_stats} warm={warm_info.get('warmed')} kw={kws}",
        )
        return {
            "source_id": source_id,
            "run_id": run_id,
            "status": "success",
            "keywords": kws,
            "clean": clean_stats,
            "detail": detail_stats,
            "warm": warm_info,
            **stats,
        }
    except Exception as e:  # noqa: BLE001
        err = str(e)
        if "captcha" in err.lower() or "rate_limited" in err.lower() or "829" in err:
            open_todo(source_id, f"source://{source_id}", title=source_id, note=err[:200])
        finish_run(run_id, status="failed", item_count=0, note=err[:500])
        return {
            "source_id": source_id,
            "run_id": run_id,
            "status": "failed",
            "error": err,
            "attempted": 0,
            "affected": 0,
            "keywords": kws,
            "warm": warm_info,
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
