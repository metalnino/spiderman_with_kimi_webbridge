"""Trial crawl: keywords x cities against cebpub bulletin list."""
from __future__ import annotations

import json
import random
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config" / "crawl_config.json").read_text(encoding="utf-8"))
OUT_DIR = ROOT / "data" / "trial"
OUT_DIR.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def fetch(url: str, retries: int = 2) -> str:
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read()
            for enc in ("utf-8", "gbk", "gb2312"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.6 * (i + 1))
    raise RuntimeError(f"fetch failed: {url} ({last})")


def parse_list(html: str) -> list[dict]:
    items = []
    # paired opens often: uuid, then home url — take uuid-like 32hex
    pattern = re.compile(
        r"<a[^>]*href=\"javascript:urlOpen\('([0-9a-fA-F]{16,})'\)\"[^>]*>(.*?)</a>",
        re.I | re.S,
    )
    for uuid, inner in pattern.findall(html):
        title = re.sub(r"<[^>]+>", "", inner)
        title = re.sub(r"\s+", " ", unescape(title)).strip()
        title = title.replace(". . .", "").strip()
        if len(title) < 4:
            continue
        items.append(
            {
                "uuid": uuid,
                "title": title,
                "detail_url": CFG["source"]["detail_url_template"].format(uuid=uuid),
            }
        )
    # meta
    page_total = None
    m = re.search(r'id="pageTotal"[^>]*value="\s*([^"]*)"', html)
    if m:
        page_total = m.group(1).strip()
    word = None
    m = re.search(r'id="word"[^>]*value="([^"]*)"', html)
    if m:
        word = urllib.parse.unquote(m.group(1))
    return items, {"page_total": page_total, "word_field": word}


def build_url(keyword: str, area_code: str, page: int = 1) -> str:
    src = CFG["source"]
    q = {
        "searchDate": time.strftime("%Y-%m-%d"),
        "dates": src["dates"],
        "word": keyword,
        "categoryId": src["category_id"],
        "industryName": "",
        "area": area_code,
        "status": "",
        "publishMedia": "",
        "sourceInfo": "",
        "showStatus": src["show_status"],
        "page": str(page),
    }
    # site historically expects word URI-encoded in query
    return src["list_url"] + "?" + urllib.parse.urlencode(q, encoding="utf-8")


def title_hits_city(title: str, city: str) -> bool:
    return city in title


def active_keywords() -> list[str]:
    kws = CFG.get("keywords")
    if isinstance(kws, dict):
        return list(kws.get("active") or kws.get("core") or [])
    return list(kws or [])


def main() -> None:
    keywords = active_keywords()
    cities = CFG["cities"]

    # Deduplicate province fetches: keyword x province, then city filter
    province_codes = {}
    for c in cities:
        province_codes.setdefault(c["area_code"], c["province"])

    raw_rows = []
    fetch_stats = []

    for kw in keywords:
        for area_code, province in province_codes.items():
            url = build_url(kw, area_code, 1)
            t0 = time.time()
            try:
                html = fetch(url)
                items, meta = parse_list(html)
                err = None
            except Exception as e:  # noqa: BLE001
                items, meta, err = [], {}, str(e)
            elapsed = round(time.time() - t0, 2)
            fetch_stats.append(
                {
                    "keyword": kw,
                    "province": province,
                    "area_code": area_code,
                    "url": url,
                    "count": len(items),
                    "page_total": meta.get("page_total"),
                    "elapsed_s": elapsed,
                    "error": err,
                }
            )
            print(f"[fetch] {kw}|{province} -> {len(items)} err={err}", flush=True)
            for it in items:
                raw_rows.append(
                    {
                        **it,
                        "keyword": kw,
                        "province": province,
                        "area_code": area_code,
                    }
                )
            time.sleep(random.uniform(0.4, 1.6))

    # City secondary filter + also keep province-level with city mention
    city_rows = []
    for row in raw_rows:
        matched_cities = [c["name"] for c in cities if c["area_code"] == row["area_code"] and title_hits_city(row["title"], c["name"])]
        # 上海省级且标题无「上海」时，直辖市可算命中
        if row["province"] == "上海" and "上海" not in matched_cities:
            matched_cities.append("上海")
        if not matched_cities:
            continue
        for city in matched_cities:
            city_rows.append({**row, "city": city})

    # Dedup by uuid+city+keyword
    seen = set()
    deduped = []
    for r in city_rows:
        key = (r["uuid"], r["city"], r["keyword"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    # Analysis
    by_kw = defaultdict(int)
    by_city = defaultdict(int)
    by_pair = defaultdict(int)
    for r in deduped:
        by_kw[r["keyword"]] += 1
        by_city[r["city"]] += 1
        by_pair[f"{r['keyword']}×{r['city']}"] += 1

    # Keyword-only baseline (no area) for noise comparison — sample first keyword only to save requests? Do all for analysis.
    baseline = []
    for kw in keywords:
        url = build_url(kw, "", 1)
        try:
            html = fetch(url)
            items, meta = parse_list(html)
            err = None
        except Exception as e:  # noqa: BLE001
            items, meta, err = [], {}, str(e)
        baseline.append(
            {
                "keyword": kw,
                "count_page1": len(items),
                "page_total": meta.get("page_total"),
                "sample_titles": [x["title"] for x in items[:5]],
                "error": err,
            }
        )
        print(f"[base] {kw} -> {len(items)} err={err}", flush=True)
        time.sleep(random.uniform(0.4, 1.6))

    # Relevance heuristic: title contains any green-plant stem
    stems = ["绿植", "绿化", "租摆", "园林", "养护", "盆栽", "花卉", "景观"]
    def relevant(title: str) -> bool:
        return any(s in title for s in stems)

    rel = [r for r in deduped if relevant(r["title"])]
    noise = [r for r in deduped if not relevant(r["title"])]

    analysis = {
        "summary": {
            "province_fetches": len(fetch_stats),
            "raw_list_items": len(raw_rows),
            "city_matched_items": len(deduped),
            "relevant_items": len(rel),
            "noise_items": len(noise),
            "unique_uuids": len({r["uuid"] for r in deduped}),
        },
        "by_keyword": dict(sorted(by_kw.items(), key=lambda x: -x[1])),
        "by_city": dict(sorted(by_city.items(), key=lambda x: -x[1])),
        "by_pair_top": dict(sorted(by_pair.items(), key=lambda x: -x[1])[:30]),
        "baseline_no_area": baseline,
        "fetch_stats": fetch_stats,
        "findings": [],
        "samples_relevant": rel[:20],
        "samples_noise": noise[:10],
    }

    # Auto findings
    if analysis["summary"]["city_matched_items"] == 0:
        analysis["findings"].append("城市二次过滤后为 0：省级结果标题多不含城市名，需改策略（省内全收再人工/AI 判城市，或详情页抽地区）。")
    weak_kw = [k for k in keywords if by_kw.get(k, 0) == 0]
    if weak_kw:
        analysis["findings"].append(f"城市命中为 0 的关键词：{', '.join(weak_kw)}")
    strong_kw = [k for k, v in analysis["by_keyword"].items() if v >= 3]
    if strong_kw:
        analysis["findings"].append(f"相对有效关键词：{', '.join(strong_kw)}")
    # Compare baseline relevance
    for b in baseline:
        titles = b.get("sample_titles") or []
        hit = sum(1 for t in titles if relevant(t))
        analysis["findings"].append(
            f"基线[{b['keyword']}] 第1页{b['count_page1']}条，样本相关约{hit}/{len(titles)}，pageTotal={b.get('page_total')}"
        )
    analysis["findings"].append(
        "站点 area 仅省级；南京/苏州同属江苏，城市区分依赖标题或详情。"
    )
    analysis["findings"].append(
        "建议下一迭代：1) 省域抓取+详情抽地区 2) 弱词可弃用或改「绿植」「绿化」 3) AI 只做相关性/城市判定"
    )

    (OUT_DIR / "items_city_matched.json").write_text(
        json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(analysis["summary"], ensure_ascii=False))
    print("WROTE", OUT_DIR)


if __name__ == "__main__":
    main()
