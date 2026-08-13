"""Login + keyword search probe for jiangsu.zhaobiao.cn."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import quote, urljoin

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import load_env  # noqa: E402

OUT = ROOT / "data" / "web" / "jiangsu_zhaobiao_probe3.json"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def main() -> None:
    env = load_env()
    user = env["JIANGSU_ZHAOBIAO_USER"]
    pwd = env["JIANGSU_ZHAOBIAO_PASS"]
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    report: dict = {}

    login_page = "https://user.zhaobiao.cn/login.html"
    r = s.get(login_page, timeout=30)
    report["login_page"] = {
        "status": r.status_code,
        "final": str(r.url),
        "len": len(r.text),
        "inputs": re.findall(r'<input[^>]*name=["\']([^"\']+)["\']', r.text, re.I),
        "actions": re.findall(r'<form[^>]*action=["\']([^"\']*)["\']', r.text, re.I),
        "scripts": re.findall(r'src=["\']([^"\']+)["\']', r.text, re.I)[:20],
        "snippet": re.sub(r"\s+", " ", r.text)[:500],
    }

    # find ajax login endpoints in page/js
    apis = re.findall(r'["\']([^"\']*(?:login|auth|signin)[^"\']*)["\']', r.text, re.I)
    report["login_apiish"] = list(dict.fromkeys(apis))[:40]

    names = report["login_page"]["inputs"]
    payload = {}
    for m in re.finditer(r"<input[^>]+>", r.text, re.I):
        tag = m.group(0)
        nm = re.search(r'name=["\']([^"\']+)["\']', tag, re.I)
        val = re.search(r'value=["\']([^"\']*)["\']', tag, re.I)
        typ = re.search(r'type=["\']([^"\']+)["\']', tag, re.I)
        if not nm:
            continue
        if typ and typ.group(1).lower() in {"submit", "button", "image"}:
            continue
        payload[nm.group(1)] = val.group(1) if val else ""
    user_key = next((n for n in names if re.search(r"user|name|account|mobile|phone|email|login", n, re.I)), None)
    pass_key = next((n for n in names if re.search(r"pass|pwd", n, re.I)), None)
    if user_key:
        payload[user_key] = user
    if pass_key:
        payload[pass_key] = pwd
    actions = report["login_page"]["actions"]
    action = urljoin(str(r.url), actions[0]) if actions else str(r.url)
    # common API guesses
    candidates = [action]
    for a in [
        "https://user.zhaobiao.cn/login",
        "https://user.zhaobiao.cn/user/login",
        "https://user.zhaobiao.cn/api/login",
        "https://user.zhaobiao.cn/login.do",
        "https://passport.zhaobiao.cn/login",
    ]:
        if a not in candidates:
            candidates.append(a)

    attempts = []
    for act in candidates[:6]:
        try:
            lr = s.post(
                act,
                data=payload,
                timeout=30,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Referer": login_page,
                    "Origin": "https://user.zhaobiao.cn",
                    "X-Requested-With": "XMLHttpRequest",
                },
                allow_redirects=True,
            )
            attempts.append(
                {
                    "action": act,
                    "status": lr.status_code,
                    "final": str(lr.url),
                    "ct": lr.headers.get("content-type"),
                    "cookie_names": list(s.cookies.keys()),
                    "body_head": lr.text[:400],
                }
            )
            if lr.status_code == 200 and (
                "success" in lr.text.lower()
                or "ok" in lr.text.lower()
                or any(k.lower().find("token") >= 0 or k.lower().find("session") >= 0 for k in s.cookies.keys())
            ):
                break
        except Exception as e:
            attempts.append({"action": act, "error": str(e)[:160]})
    report["login_attempts"] = attempts
    report["cookies_after_login"] = list(s.cookies.keys())

    # search
    kw = "绿化养护"
    search_urls = [
        f"https://jiangsu.zhaobiao.cn/ssearch_q_{quote(kw)}_qs_h_s_01_pro_320000_f_03_p_1.html",
        f"https://jiangsu.zhaobiao.cn/ssearch_q_{kw}_pro_320000_p_1.html",
        "https://jiangsu.zhaobiao.cn/bid.html",
    ]
    # form search on home
    try:
        hr = s.post(
            "https://jiangsu.zhaobiao.cn/",
            data={"searchwords": kw},
            timeout=30,
            headers={"Referer": "https://jiangsu.zhaobiao.cn/"},
            allow_redirects=True,
        )
        search_urls.insert(0, str(hr.url))
        report["home_search_post"] = {"final": str(hr.url), "status": hr.status_code, "len": len(hr.text)}
    except Exception as e:
        report["home_search_post"] = {"error": str(e)[:160]}

    searches = []
    for u in search_urls:
        try:
            sr = s.get(u, timeout=30, headers={"Referer": "https://jiangsu.zhaobiao.cn/"})
            html = sr.text
            items = []
            for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S):
                href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2))
                title = re.sub(r"\s+", " ", title).strip()
                if len(title) >= 10 and ("html" in href or "bid" in href or "info" in href):
                    items.append({"title": title[:120], "href": href[:200]})
                    if len(items) >= 15:
                        break
            searches.append(
                {
                    "url": u,
                    "status": sr.status_code,
                    "final": str(sr.url),
                    "len": len(html),
                    "items": items[:10],
                    "need_login": bool(re.search(r"请登录|免费试用|登录后", html[:3000])),
                }
            )
        except Exception as e:
            searches.append({"url": u, "error": str(e)[:160]})
    report["searches"] = searches

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:6000])
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
