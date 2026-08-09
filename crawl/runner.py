from __future__ import annotations

from crawl.config_loader import sources_cfg, trial_keywords
from crawl.db_store import finish_run, start_run, upsert_notices
from crawl.sources import get_source


def run_source(source_id: str, *, keywords: list[str] | None = None, max_pages: int = 1) -> dict:
    kws = keywords or trial_keywords()
    # P0 控规模：默认最多 2 个词
    kws = kws[:2]
    src = get_source(source_id)
    run_id = start_run(source_id)
    try:
        notices = list(src.fetch(kws, max_pages=max_pages))
        stats = upsert_notices(notices)
        finish_run(
            run_id,
            status="success",
            item_count=stats["attempted"],
            note=f"upsert affected≈{stats['affected']} keywords={kws}",
        )
        return {
            "source_id": source_id,
            "run_id": run_id,
            "status": "success",
            "keywords": kws,
            **stats,
        }
    except Exception as e:  # noqa: BLE001
        finish_run(run_id, status="failed", item_count=0, note=str(e)[:500])
        return {
            "source_id": source_id,
            "run_id": run_id,
            "status": "failed",
            "error": str(e),
            "attempted": 0,
            "affected": 0,
            "keywords": kws,
        }


def run_incremental(*, sources: list[str] | None = None, max_pages: int = 1) -> list[dict]:
    cfg = sources_cfg()
    order = sources or ["ggzy", "chinabidding", "cebpub", "ccgp"]
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
