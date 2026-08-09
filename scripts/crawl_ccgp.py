"""Trial crawl: 中国政府采购网 list + sample detail amounts."""
from __future__ import annotations

import json
import re
import urllib.parse
from collections import defaultdict
from html import unescape
from pathlib import Path

from http_util import (
    ROOT,
    active_cities,
    fetch_text,
    load_json,
    match_cities,
    sleep_jitter,
    trial_keywords,
)

OUT = ROOT / "data" / "trial_multi"
SOURCES = load_json(ROOT / "config" / "sources.json")


def build_list_url(kw: str, page: int, time_type: str) -> str:
    q = {
        "searchtype": "1",
        "page_index": str(page),
        "bidSort": "0",
        "buyerName": "",
        "projectId": "",
        "pinMu": "0",
        "bidType": "0",
        "dbselect": "bidx",
        "kw": kw,
        "timeType": time_type,
    }
    return "https://search.ccgp.gov.cn/bxsearch?" + urllib.parse.urlencode(q)


def is_rate_limited(html: str) -> bool:
    return "访问过于频繁" in html or "频繁访问" in (re.search(r"<title>([^<]+)", html) or [None, ""])[1]


def parse_list(html: str) -> tuple[list[dict], dict]:
    if is_rate_limited(html):
        return [], {"total": None, "rate_limited": True}

    items = []
    # result total
    total = None
    m = re.search(r"共找到\s*([\d,]+)\s*条", html)
    if m:
        total = int(m.group(1).replace(",", ""))

    # each li typically contains a.cggg / www.ccgp.gov.cn/cggg link
    blocks = re.split(r"<li\b", html, flags=re.I)
    for block in blocks[1:]:
        link = re.search(
            r'href="(https?://www\.ccgp\.gov\.cn/cggg/[^"]+\.htm)"[^>]*>(.*?)</a>',
            block,
            re.I | re.S,
        )
        if not link:
            link = re.search(
                r'href="(http://www\.ccgp\.gov\.cn/cggg/[^"]+\.htm)"[^>]*>(.*?)</a>',
                block,
                re.I | re.S,
            )
        if not link:
            continue
        href = link.group(1)
        title = re.sub(r"<[^>]+>", "", link.group(2))
        title = re.sub(r"\s+", " ", unescape(title)).strip()
        if len(title) < 4:
            continue
        text = re.sub(r"<[^>]+>", " ", block)
        text = re.sub(r"\s+", " ", unescape(text))
        buyer = None
        mb = re.search(r"采购人[：:]\s*([^|]+)", text)
        if mb:
            buyer = mb.group(1).strip()[:80]
        agency = None
        ma = re.search(r"代理机构[：:]\s*([^|]+)", text)
        if ma:
            agency = ma.group(1).strip()[:80]
        pub = None
        mp = re.search(r"(20\d{2}\.\d{2}\.\d{2}\s+\d{2}:\d{2}:\d{2})", text)
        if mp:
            pub = mp.group(1).replace(".", "-")
        region = None
        # often "公开招标公告 | 上海 |" style near end
        mr = re.search(
            r"(公开招标|竞争性磋商|竞争性谈判|询价|单一来源|中标|成交|更正|废标|终止)公告?\s*\|\s*([^\s|]+)\s*\|",
            text,
        )
        if mr:
            region = mr.group(2).strip()
        notice_type = None
        mt = re.search(
            r"(公开招标公告|竞争性磋商公告|询价公告|中标公告|成交公告|更正公告|废标公告|终止公告|其他公告)",
            text,
        )
        if mt:
            notice_type = mt.group(1)
        items.append(
            {
                "title": title,
                "detail_url": href.replace("http://", "https://"),
                "publish_date": pub,
                "buyer": buyer,
                "agency": agency,
                "region": region,
                "notice_type": notice_type,
                "source": "中国政府采购网",
                "source_id": "ccgp",
            }
        )
    # dedupe by url within page
    seen = set()
    uniq = []
    for it in items:
        if it["detail_url"] in seen:
            continue
        seen.add(it["detail_url"])
        uniq.append(it)
    return uniq, {"total": total}


def parse_detail(html: str) -> dict:
    text = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", unescape(text))
    out = {}
    for lab, key in [
        (r"采购项目编号[：:]\s*([A-Za-z0-9\-_/]+)", "project_code"),
        (r"项目编号[：:]\s*([A-Za-z0-9\-_/]+)", "project_code"),
        (r"采购人[：:]\s*([^。；;]{2,80})", "buyer"),
        (r"预算金额[：:]\s*([^\s。；;]+)", "amount_text"),
        (r"预算[：:]\s*([0-9,.]+)\s*元", "amount_text"),
    ]:
        m = re.search(lab, text)
        if m and key not in out:
            out[key] = m.group(1).strip()
    # deadline
    m = re.search(r"于\s*(20\d{2}年\d{1,2}月\d{1,2}日[^。]{0,20})", text)
    if m:
        out["deadline_hint"] = m.group(1)[:60]
    amt = out.get("amount_text")
    if amt:
        num = re.search(r"([\d,.]+)", amt)
        if num:
            try:
                out["amount"] = float(num.group(1).replace(",", ""))
            except ValueError:
                pass
    out["text_len"] = len(text)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = SOURCES["ccgp"]
    defaults = SOURCES["defaults"]
    keywords = trial_keywords(SOURCES)
    cities = active_cities()
    max_pages = int(defaults.get("max_pages_per_keyword") or 2)
    detail_n = int(defaults.get("detail_sample_per_keyword") or 3)
    dmin, dmax = defaults.get("delay_ms_min", 600), defaults.get("delay_ms_max", 1800)

    rows = []
    stats = []
    # ccgp 易触发「访问过于频繁」，拉长间隔并做退避重试
    dmin, dmax = max(dmin, 2500), max(dmax, 5000)
    for kw in keywords:
        for page in range(1, max_pages + 1):
            url = build_list_url(kw, page, str(cfg.get("time_type") or "5"))
            err = None
            items, meta = [], {}
            for attempt in range(3):
                try:
                    html = fetch_text(url, headers={"Referer": "https://www.ccgp.gov.cn/"})
                    items, meta = parse_list(html)
                    if meta.get("rate_limited"):
                        err = "rate_limited"
                        print(f"[ccgp] rate-limited, sleep 45s (attempt {attempt+1})", flush=True)
                        import time as _t

                        _t.sleep(45)
                        continue
                    err = None
                    break
                except Exception as e:  # noqa: BLE001
                    err = str(e)
                    sleep_jitter(dmin, dmax)
            stats.append(
                {
                    "keyword": kw,
                    "page": page,
                    "url": url,
                    "count": len(items),
                    "total": meta.get("total"),
                    "error": err,
                }
            )
            print(f"[ccgp] {kw} p{page} -> {len(items)} total={meta.get('total')} err={err}", flush=True)
            for it in items:
                city_hits = match_cities(it["title"], cities)
                if not city_hits and it.get("region"):
                    for c in cities:
                        if c["province"] in (it["region"] or "") or c["name"] in (it["region"] or ""):
                            city_hits.append(c["name"])
                rows.append({**it, "keyword": kw, "cities": city_hits or []})
            sleep_jitter(dmin, dmax)
            if err == "rate_limited":
                break
            if meta.get("total") is not None and meta["total"] == 0:
                break
            if not items:
                break

    # sample details
    if cfg.get("fetch_detail"):
        by_kw = defaultdict(list)
        for r in rows:
            by_kw[r["keyword"]].append(r)
        for kw, lst in by_kw.items():
            for r in lst[:detail_n]:
                try:
                    html = fetch_text(r["detail_url"], headers={"Referer": "https://search.ccgp.gov.cn/"})
                    det = parse_detail(html)
                    r["detail"] = det
                    if det.get("amount") is not None:
                        r["amount"] = det["amount"]
                    if det.get("amount_text"):
                        r["amount_text"] = det["amount_text"]
                    if det.get("buyer") and not r.get("buyer"):
                        r["buyer"] = det["buyer"]
                    if det.get("project_code"):
                        r["project_code"] = det["project_code"]
                    print(f"[ccgp-detail] {r['title'][:40]} amount={r.get('amount_text')}", flush=True)
                except Exception as e:  # noqa: BLE001
                    r["detail_error"] = str(e)
                sleep_jitter(dmin, dmax)

    # dedupe by detail_url
    seen = set()
    deduped = []
    for r in rows:
        u = r["detail_url"]
        if u in seen:
            continue
        seen.add(u)
        deduped.append(r)

    summary = {
        "source": "ccgp",
        "keywords": keywords,
        "list_items": len(deduped),
        "with_amount": sum(1 for r in deduped if r.get("amount") or r.get("amount_text")),
        "city_tagged": sum(1 for r in deduped if r.get("cities")),
        "stats": stats,
        "sample_titles": [r["title"] for r in deduped[:10]],
    }
    (OUT / "ccgp_items.json").write_text(json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "ccgp_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("list_items", "with_amount", "city_tagged")}, ensure_ascii=False))
    print("WROTE", OUT / "ccgp_items.json")


if __name__ == "__main__":
    main()
