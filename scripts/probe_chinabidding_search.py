"""Deeper probe: search URLs, list pages, detail pages for chinabidding."""
from __future__ import annotations

import json
import re
import ssl
import time
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "chinabidding"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
CTX = ssl._create_unverified_context()
KW = "绿化养护"


def fetch(url: str, timeout=30) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json,*/*", "Referer": "https://www.chinabidding.com.cn/"})
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            raw = r.read()
            final = r.geturl()
            ctype = r.headers.get("Content-Type", "")
            status = r.status
        text = raw.decode("utf-8", "ignore")
        if "charset=gbk" in ctype.lower() or "gb2312" in ctype.lower():
            text = raw.decode("gbk", "ignore")
        return {"ok": True, "status": status, "final": final, "ctype": ctype, "len": len(text), "text": text}
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)}


def summarize_html(text: str, base: str) -> dict:
    title_m = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
    title = re.sub(r"\s+", " ", unescape(title_m.group(1))).strip() if title_m else ""
    # detail-like links
    links = []
    for h, inner in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, re.I | re.S):
        t = re.sub(r"<[^>]+>", "", inner)
        t = re.sub(r"\s+", " ", unescape(t)).strip()
        if len(t) < 6:
            continue
        full = urllib.parse.urljoin(base, h)
        if re.search(r"zbgg|zfcg|pageInfo|search|招标|绿化|养护|租摆", t + full):
            links.append({"t": t[:80], "h": full[:300]})
        if len(links) >= 25:
            break
    apis = sorted(set(re.findall(r"[\"']/[^\"']*(?:search|list|api|query)[^\"']*", text, re.I)))[:40]
    apis += sorted(set(re.findall(r"https?://[^\"'\\s]+(?:search|list|api)[^\"'\\s]*", text, re.I)))[:40]
    money = re.findall(r"(预算|金额|限价)[^\d]{0,6}[￥¥]?[\d,.]+\s*万?元?", text)[:10]
    login_wall = bool(re.search(r"登录后|开通会员|VIP|付费|权限", text))
    return {
        "title": title,
        "links": links,
        "apis": apis[:50],
        "money_hits": money,
        "login_wall": login_wall,
        "has_el_table": "el-table" in text or "el-pagination" in text,
    }


def main():
    q = urllib.parse.quote(KW)
    candidates = [
        f"https://www.chinabidding.com.cn/search?keyword={q}",
        f"https://www.chinabidding.com.cn/search.html?keyword={q}",
        f"https://www.chinabidding.cn/search/?keywords={q}",
        f"https://www.chinabidding.cn/search.html?keywords={q}",
        f"https://www.chinabidding.com.cn/zb/search?wd={q}",
        # known channel pages from homepage
        "https://www.chinabidding.cn/zbgg/",
        "https://www.chinabidding.cn/zfcg/",
        # sample details from homepage probe
        "https://www.chinabidding.cn/zfcg/U-vzsEKyK.html",
        "https://www.chinabidding.cn/zbgg/U-vzsE6PC.html",
        "https://www.chinabidding.com.cn/pageInfoSsr/3000000016066/1087000001447961",
    ]

    report = {"keyword": KW, "pages": []}
    for u in candidates:
        print("[get]", u, flush=True)
        r = fetch(u)
        item = {"url": u, "ok": r.get("ok"), "status": r.get("status"), "final": r.get("final"), "error": r.get("error"), "ctype": r.get("ctype"), "len": r.get("len")}
        if r.get("ok"):
            item["summary"] = summarize_html(r["text"], r.get("final") or u)
            # save one detail sample
            if "/zfcg/" in u or "/zbgg/" in u or "pageInfoSsr" in u:
                (OUT / ("sample_" + re.sub(r"[^a-zA-Z0-9]+", "_", u)[-40:] + ".html")).write_text(r["text"][:200000], encoding="utf-8")
        report["pages"].append(item)
        time.sleep(0.8)

    # also scan homepage JS for search endpoint
    home = fetch("https://www.chinabidding.com.cn/")
    if home.get("ok"):
        js_urls = re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', home["text"])[:30]
        hits = []
        for j in js_urls:
            ju = urllib.parse.urljoin("https://www.chinabidding.com.cn/", j)
            jr = fetch(ju)
            if not jr.get("ok"):
                continue
            paths = sorted(set(re.findall(r"[\"'](/[^\"']*(?:search|bid|list|query)[^\"']*)[\"']", jr["text"], re.I)))
            if paths:
                hits.append({"js": ju, "paths": paths[:40]})
        report["js_search_hints"] = hits

    path = OUT / "search_probe.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", path)


if __name__ == "__main__":
    main()
