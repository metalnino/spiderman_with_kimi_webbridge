from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def extract_items(html: str) -> list[dict]:
    items = []
    # common list patterns: title + date
    for m in re.finditer(
        r'<a[^>]+href="([^"]+)"[^>]*title="([^"]+)"[^>]*>|'
        r'<a[^>]+href="([^"]+)"[^>]*>\s*([^<]{8,120})\s*</a>',
        html,
        re.I,
    ):
        if m.group(1) and m.group(2):
            href, title = m.group(1), m.group(2)
        else:
            href, title = m.group(3), m.group(4)
        title = re.sub(r"\s+", " ", title or "").strip()
        href = (href or "").strip()
        if not title or not href:
            continue
        if href.startswith("javascript"):
            continue
        if any(x in href for x in ["login", "register", "help", "css", "js"]):
            continue
        items.append({"title": title[:160], "href": href[:260]})
    # dedupe
    seen = set()
    out = []
    for it in items:
        k = it["href"]
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out[:30]


def main() -> None:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    s.get("https://jiangsu.zhaobiao.cn/", timeout=30)
    kw = "绿化养护"
    urls = [
        "https://jiangsu.zhaobiao.cn/bid.html",
        f"https://jiangsu.zhaobiao.cn/ssearch_q_{quote(kw)}_qs_h_s_01_pro_320000_f_03_p_1.html",
        f"https://jiangsu.zhaobiao.cn/ssearch_q_{quote(kw)}_pro_320000_p_1.html",
        f"https://jiangsu.zhaobiao.cn/searchwords?searchwords={quote(kw)}",
    ]
    # try GET with query on search form target from homepage
    home = s.get("https://jiangsu.zhaobiao.cn/", timeout=30).text
    forms = re.findall(r'<form[^>]*>(.*?)</form>', home, re.I | re.S)
    report = {"forms_count": len(forms)}
    for f in forms[:3]:
        if "searchwords" in f:
            action = re.search(r'action=["\']([^"\']*)["\']', f, re.I)
            report["search_form_action"] = action.group(1) if action else ""
            report["search_form_snippet"] = re.sub(r"\s+", " ", f)[:400]

    results = {}
    for u in urls:
        r = s.get(u, timeout=30, headers={"Referer": "https://jiangsu.zhaobiao.cn/"})
        items = extract_items(r.text)
        results[u] = {
            "status": r.status_code,
            "final": str(r.url),
            "len": len(r.text),
            "items": items[:12],
            "has_kw": kw in r.text,
            "locked": bool(re.search(r"登录后|请登录|开通会员|VIP", r.text[:12000])),
        }
    # POST searchwords
    action = report.get("search_form_action") or "https://jiangsu.zhaobiao.cn/"
    if action.startswith("/"):
        action = "https://jiangsu.zhaobiao.cn" + action
    pr = s.post(
        action,
        data={"searchwords": kw},
        timeout=30,
        headers={"Referer": "https://jiangsu.zhaobiao.cn/", "Content-Type": "application/x-www-form-urlencoded"},
        allow_redirects=True,
    )
    results["POST_searchwords"] = {
        "action": action,
        "status": pr.status_code,
        "final": str(pr.url),
        "len": len(pr.text),
        "items": extract_items(pr.text)[:12],
        "locked": bool(re.search(r"登录后|请登录|开通会员|VIP", pr.text[:12000])),
    }
    report["results"] = results
    path = ROOT / "data" / "web" / "jiangsu_zhaobiao_probe5.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:7000])
    print("WROTE", path)


if __name__ == "__main__":
    main()
