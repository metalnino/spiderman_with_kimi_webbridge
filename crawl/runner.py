from __future__ import annotations

from crawl.captcha_queue import open_todo
from crawl.config_loader import sources_cfg
from crawl.db_store import finish_run, start_run, upsert_notices
from crawl.keywords import enabled_keywords
from crawl.pipeline.apply_clean import refresh_clean_status
from crawl.sources import get_source
from crawl.warm_session import warm_source


def run_source(source_id: str, *, keywords: list[str] | None = None, max_pages: int = 1) -> dict:
    kws = keywords or enabled_keywords()
    kws = kws[:2]
    src = get_source(source_id)
    warm_info = warm_source(source_id, src.http)
    run_id = start_run(source_id)
    try:
        notices = list(src.fetch(kws, max_pages=max_pages))
        stats = upsert_notices(notices)
        clean_stats = refresh_clean_status(limit=max(200, stats["attempted"] * 3))
        # cebpub 详情验证码：为样本登记待办（不阻塞列表）
        if source_id == "cebpub":
            for n in notices[:3]:
                if n.detail_url:
                    open_todo(source_id, n.detail_url, n.title, note="detail_may_need_captcha")
        finish_run(
            run_id,
            status="success",
            item_count=stats["attempted"],
            note=f"upsert≈{stats['affected']} clean={clean_stats} warm={warm_info.get('warmed')} kw={kws}",
        )
        return {
            "source_id": source_id,
            "run_id": run_id,
            "status": "success",
            "keywords": kws,
            "clean": clean_stats,
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
    order = sources or ["ggzy", "chinabidding", "cebpub", "ccgp", "jsggzy"]
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
