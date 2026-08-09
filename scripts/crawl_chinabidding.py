"""Trial crawl: 采招网 list-only via info_search (no login detail)."""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from http_util import (
    ROOT,
    active_cities,
    fetch_json,
    load_json,
    match_cities,
    sleep_jitter,
    trial_keywords,
)

OUT = ROOT / "data" / "trial_multi"
SOURCES = load_json(ROOT / "config" / "sources.json")


def info_search(kw: str, page: int, rp: int) -> dict:
    api = SOURCES["chinabidding"]["list_api"]
    q = urllib.parse.urlencode(
        {
            "keyword": kw,
            "page": str(page),
            "rp": str(rp),
            "device": "zbdt001",
            "cpcode": "zbdt001",
        }
    )
    url = f"{api}?{q}"
    return fetch_json(
        url,
        headers={
            "Referer": "https://www.chinabidding.com.cn/search",
            "Accept": "application/json,text/plain,*/*",
        },
    ), url


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = SOURCES["chinabidding"]
    defaults = SOURCES["defaults"]
    keywords = trial_keywords(SOURCES)
    cities = active_cities()
    max_pages = int(defaults.get("max_pages_per_keyword") or 2)
    rp = int(cfg.get("rp") or 15)
    dmin, dmax = defaults.get("delay_ms_min", 600), defaults.get("delay_ms_max", 1800)
    detail_host = cfg.get("detail_host") or "https://www.chinabidding.cn"

    rows = []
    stats = []
    for kw in keywords:
        for page in range(1, max_pages + 1):
            err = None
            total = None
            items = []
            url = None
            try:
                data, url = info_search(kw, page, rp)
                total = data.get("total")
                items = data.get("relatedList") or data.get("list") or []
            except Exception as e:  # noqa: BLE001
                err = str(e)
            stats.append(
                {
                    "keyword": kw,
                    "page": page,
                    "url": url,
                    "count": len(items),
                    "total": total,
                    "error": err,
                }
            )
            print(f"[chinabidding] {kw} p{page} -> {len(items)} total={total} err={err}", flush=True)
            for it in items:
                if not isinstance(it, dict):
                    continue
                path = it.get("url") or ""
                detail_url = None
                if path.startswith("/"):
                    detail_url = detail_host + path
                elif str(path).startswith("http"):
                    detail_url = path
                title = it.get("title") or ""
                city_hits = match_cities(title, cities)
                rows.append(
                    {
                        "id": it.get("id"),
                        "title": title,
                        "publish_date": it.get("publish_date"),
                        "area_id": it.get("area_id"),
                        "category_id": it.get("category_id"),
                        "table_name": it.get("table_name"),
                        "table_name2": it.get("table_name2"),
                        "detail_url": detail_url,
                        "keyword": kw,
                        "cities": city_hits,
                        "source": "中国采购与招标网",
                        "source_id": "chinabidding",
                        "detail_mode": "list_only_login_wall",
                    }
                )
            sleep_jitter(dmin, dmax)
            if not items:
                break

    seen = set()
    deduped = []
    for r in rows:
        key = r.get("id") or r.get("detail_url") or r.get("title")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    summary = {
        "source": "chinabidding",
        "mode": "list_only",
        "keywords": keywords,
        "list_items": len(deduped),
        "city_tagged": sum(1 for r in deduped if r.get("cities")),
        "stats": stats,
        "sample_titles": [r["title"] for r in deduped[:10]],
        "note": "详情需账号；本轮不抓详情字段",
    }
    (OUT / "chinabidding_items.json").write_text(
        json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "chinabidding_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: summary[k] for k in ("list_items", "city_tagged")}, ensure_ascii=False))
    print("WROTE", OUT / "chinabidding_items.json")


if __name__ == "__main__":
    main()
