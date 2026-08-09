"""Trial crawl: 全国公共资源交易平台 getTradList."""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from http_util import (
    ROOT,
    UA,
    active_cities,
    fetch_bytes,
    load_json,
    match_cities,
    province_code_map,
    sleep_jitter,
    trial_keywords,
)

OUT = ROOT / "data" / "trial_multi"
SOURCES = load_json(ROOT / "config" / "sources.json")


def get_trad_list(kw: str, page: int, deal_time: str, referer: str) -> dict:
    api = SOURCES["ggzy"]["api"]
    body = urllib.parse.urlencode(
        {
            "FINDTXT": kw,
            "PAGENUMBER": str(page),
            "DEAL_TIME": deal_time,
        }
    ).encode()
    status, raw, _ = fetch_bytes(
        api,
        data=body,
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": referer,
            "Origin": "https://www.ggzy.gov.cn",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    data = json.loads(raw.decode("utf-8", "ignore"))
    data["_http_status"] = status
    return data


def normalize_record(rec: dict, kw: str) -> dict:
    rid = rec.get("id") or ""
    href = rec.get("url") or ""
    if href.startswith("/"):
        detail_url = "https://www.ggzy.gov.cn" + href
    elif str(href).startswith("http"):
        detail_url = href
    else:
        detail_url = None

    province_code = str(rec.get("province") or "")
    title = rec.get("title") or ""
    return {
        "id": rid,
        "title": title,
        "publish_date": rec.get("publishTime") or rec.get("addTime"),
        "province_code": province_code,
        "province_text": rec.get("provinceText"),
        "city_text": rec.get("cityText"),
        "platform": rec.get("transactionSourcesPlatformText"),
        "business_type": rec.get("businessTypeText"),
        "stage_type": rec.get("informationTypeText") or rec.get("stageTypeText"),
        "project_code": rec.get("tenderProjectCode"),
        "detail_url": detail_url,
        "keyword": kw,
        "source": "全国公共资源交易平台",
        "source_id": "ggzy",
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = SOURCES["ggzy"]
    defaults = SOURCES["defaults"]
    keywords = trial_keywords(SOURCES)
    cities = active_cities()
    code_to_prov = province_code_map(cities)
    # expand: map province codes we care about
    want_codes = {c["area_code"] for c in cities}
    max_pages = int(defaults.get("max_pages_per_keyword") or 2)
    dmin, dmax = defaults.get("delay_ms_min", 600), defaults.get("delay_ms_max", 1800)
    deal_time = str(cfg.get("deal_time") or "05")
    referer = cfg.get("referer") or "https://www.ggzy.gov.cn/deal/dealList.html"

    rows = []
    stats = []
    for kw in keywords:
        for page in range(1, max_pages + 1):
            err = None
            code = None
            recs = []
            total = None
            try:
                data = get_trad_list(kw, page, deal_time, referer)
                code = data.get("code")
                if code == 829:
                    err = "captcha_829"
                    stats.append({"keyword": kw, "page": page, "code": code, "error": err, "count": 0})
                    print(f"[ggzy] {kw} p{page} CAPTCHA 829 — stop keyword", flush=True)
                    break
                if code != 200:
                    err = f"code={code} msg={data.get('message')}"
                else:
                    payload = data.get("data") or {}
                    recs = payload.get("records") or []
                    total = payload.get("total") or payload.get("ttlrow")
            except Exception as e:  # noqa: BLE001
                err = str(e)
            stats.append(
                {
                    "keyword": kw,
                    "page": page,
                    "code": code,
                    "count": len(recs),
                    "total": total,
                    "error": err,
                }
            )
            print(f"[ggzy] {kw} p{page} -> {len(recs)} total={total} err={err}", flush=True)
            for rec in recs:
                item = normalize_record(rec, kw)
                prov_name = code_to_prov.get(item["province_code"])
                ptext = item.get("province_text") or ""
                for c in cities:
                    if c["province"] in ptext:
                        prov_name = c["province"]
                        break
                city_hits = match_cities(item["title"], cities, prov_name)
                if item.get("city_text"):
                    for c in cities:
                        if c["name"] in (item["city_text"] or "") and c["name"] not in city_hits:
                            city_hits.append(c["name"])
                item["in_target_province"] = item["province_code"] in want_codes
                item["province"] = prov_name
                item["cities"] = city_hits
                rows.append(item)
            sleep_jitter(dmin, dmax)
            if not recs:
                break

    # If detail_url still empty, try to recover from title-linked pattern in raw — store id for later
    seen = set()
    deduped = []
    for r in rows:
        key = r.get("id") or r.get("title")
        if key in seen:
            continue
        seen.add(key)
        # drop bulky raw_keys from final optional
        deduped.append(r)

    summary = {
        "source": "ggzy",
        "keywords": keywords,
        "list_items": len(deduped),
        "in_target_province": sum(1 for r in deduped if r.get("in_target_province")),
        "city_tagged": sum(1 for r in deduped if r.get("cities")),
        "with_detail_url": sum(1 for r in deduped if r.get("detail_url")),
        "captcha_hits": sum(1 for s in stats if s.get("error") == "captcha_829"),
        "stats": stats,
        "sample_titles": [r["title"] for r in deduped[:10]],
    }
    (OUT / "ggzy_items.json").write_text(json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "ggzy_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("list_items", "in_target_province", "city_tagged", "captcha_hits")}, ensure_ascii=False))
    print("WROTE", OUT / "ggzy_items.json")


if __name__ == "__main__":
    main()
