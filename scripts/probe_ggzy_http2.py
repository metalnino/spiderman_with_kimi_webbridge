"""Fetch ggzy search page and try API variants."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "multi_site"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
KEYWORDS = ["绿植租摆", "绿化养护"]


def fetch(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "ignore")


def try_api(kw: str) -> dict:
    variants = [
        ("POST form", "https://www.ggzy.gov.cn/information/pubTradingInfo/getTradList", {"FINDTXT": kw, "PAGENUMBER": "1"}),
        ("POST form DEAL_TIME", "https://www.ggzy.gov.cn/information/pubTradingInfo/getTradList", {"FINDTXT": kw, "PAGENUMBER": "1", "DEAL_TIME": "05"}),
        ("POST captcha path", "https://www.ggzy.gov.cn/information/captcha", {}),
    ]
    results = []
    for name, api, params in variants:
        try:
            body = urllib.parse.urlencode(params).encode() if params else b""
            req = urllib.request.Request(
                api,
                data=body if params else None,
                method="POST" if params or "captcha" in api else "GET",
                headers={
                    "User-Agent": UA,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": "https://www.ggzy.gov.cn/deal/dealList.html",
                    "Origin": "https://www.ggzy.gov.cn",
                },
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode("utf-8", "ignore")
                results.append({"name": name, "status": r.status, "body_head": raw[:300]})
        except Exception as e:
            results.append({"name": name, "error": str(e)})
    return {"api_tries": results}


def main():
    report = {"keywords": {}}
    for kw in KEYWORDS:
        q = urllib.parse.quote(kw)
        search_url = f"https://www.ggzy.gov.cn/deal/dealList.html?DEAL_TIME=05&FINDTXT={q}"
        entry = {"search_url": search_url}
        try:
            status, html = fetch(search_url)
            entry["page_status"] = status
            entry["page_len"] = len(html)
            entry["is_405"] = "405" in html[:500]
            entry["kw_in_html"] = kw in html
            # extract list items from rendered template or links
            links = re.findall(
                r'href="(/information/deal/html/[^"]+)"[^>]*>([^<]+)',
                html,
            )
            matched = [{"h": h, "t": t.strip()} for h, t in links if kw in t or re.search(r"绿化|绿植|租摆|养护", t)]
            entry["info_links"] = matched[:15]
            # vue myFindTxt default
            m = re.search(r"myFindTxt\s*:\s*['\"]([^'\"]*)['\"]", html)
            entry["vue_findtxt"] = m.group(1) if m else None
            m2 = re.search(r"FINDTXT=([^&\"']+)", search_url)
            entry["api"] = try_api(kw)
        except Exception as e:
            entry["error"] = str(e)
        report["keywords"][kw] = entry

    # default list page sample
    try:
        _, html = fetch("https://www.ggzy.gov.cn/deal/dealList.html")
        entry = {}
        # sample first list row pattern from vue template
        for pat in [r"\{\{[^}]+\}\}", r"record\.", r"records"]:
            entry[pat] = len(re.findall(pat, html))
        report["dealList_template_hints"] = entry
    except Exception as e:
        report["dealList_error"] = str(e)

    path = OUT / "ggzy_http_detail.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", path)
    for kw, v in report["keywords"].items():
        print(kw, "status=", v.get("page_status"), "405=", v.get("is_405"), "links=", len(v.get("info_links") or []))


if __name__ == "__main__":
    main()
