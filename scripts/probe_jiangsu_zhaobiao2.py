"""Faster probe for jiangsu.zhaobiao.cn using requests."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import urljoin

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import load_env  # noqa: E402

OUT = ROOT / "data" / "web" / "jiangsu_zhaobiao_probe2.json"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def main() -> None:
    env = load_env()
    user = env.get("JIANGSU_ZHAOBIAO_USER", "")
    pwd = env.get("JIANGSU_ZHAOBIAO_PASS", "")
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    )
    report: dict = {"has_creds": bool(user and pwd)}

    def get(url: str):
        r = s.get(url, timeout=25, allow_redirects=True)
        return r

    pages = {}
    for u in [
        "https://jiangsu.zhaobiao.cn/",
        "http://jiangsu.zhaobiao.cn/",
        "https://www.zhaobiao.cn/",
        "https://www.zhaobiao.cn/login.html",
        "https://passport.zhaobiao.cn/",
        "https://user.zhaobiao.cn/",
        "https://s.zhaobiao.cn/",
    ]:
        try:
            r = get(u)
            text = r.text
            pages[u] = {
                "status": r.status_code,
                "final": str(r.url),
                "len": len(text),
                "title": (re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S) or [None, ""])[1][:80],
                "has_password": 'type="password"' in text.lower(),
                "form_actions": re.findall(r'<form[^>]*action=["\']([^"\']*)["\']', text, re.I)[:10],
                "input_names": re.findall(r'<input[^>]*name=["\']([^"\']+)["\']', text, re.I)[:40],
                "apiish": list(
                    dict.fromkeys(re.findall(r'["\']((?:https?:)?//[^"\']+|/[a-z][^"\']*(?:login|search|api)[^"\']*)["\']', text, re.I))
                )[:30],
            }
        except Exception as e:
            pages[u] = {"error": str(e)[:200]}
    report["pages"] = pages

    # attempt login on any page with password field
    login_url = None
    for u, info in pages.items():
        if info.get("has_password"):
            login_url = info.get("final") or u
            break
    if not login_url:
        # try known patterns
        for u in [
            "https://www.zhaobiao.cn/login.html",
            "https://passport.zhaobiao.cn/login",
            "https://user.zhaobiao.cn/login.html",
        ]:
            try:
                r = get(u)
                if 'type="password"' in r.text.lower():
                    login_url = str(r.url)
                    pages[u] = {
                        "status": r.status_code,
                        "final": str(r.url),
                        "len": len(r.text),
                        "has_password": True,
                        "input_names": re.findall(r'<input[^>]*name=["\']([^"\']+)["\']', r.text, re.I)[:40],
                        "form_actions": re.findall(r'<form[^>]*action=["\']([^"\']*)["\']', r.text, re.I)[:10],
                    }
                    break
            except Exception as e:
                pages[u] = {"error": str(e)[:200]}

    if login_url and user and pwd:
        r = get(login_url)
        names = re.findall(r'<input[^>]*name=["\']([^"\']+)["\']', r.text, re.I)
        actions = re.findall(r'<form[^>]*action=["\']([^"\']*)["\']', r.text, re.I)
        payload = {}
        # collect hidden
        for m in re.finditer(
            r'<input[^>]*type=["\']hidden["\'][^>]*>|<input[^>]*name=["\']([^"\']+)["\'][^>]*type=["\']hidden["\'][^>]*>',
            r.text,
            re.I,
        ):
            tag = m.group(0)
            nm = re.search(r'name=["\']([^"\']+)["\']', tag, re.I)
            val = re.search(r'value=["\']([^"\']*)["\']', tag, re.I)
            if nm:
                payload[nm.group(1)] = val.group(1) if val else ""
        user_key = next((n for n in names if re.search(r"user|name|account|mobile|phone|email|loginid", n, re.I)), None)
        pass_key = next((n for n in names if re.search(r"pass|pwd", n, re.I)), None)
        if user_key:
            payload[user_key] = user
        if pass_key:
            payload[pass_key] = pwd
        action = urljoin(str(r.url), actions[0]) if actions else str(r.url)
        try:
            lr = s.post(
                action,
                data=payload,
                timeout=25,
                headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": str(r.url)},
                allow_redirects=True,
            )
            report["login"] = {
                "action": action,
                "user_key": user_key,
                "pass_key": pass_key,
                "status": lr.status_code,
                "final": str(lr.url),
                "len": len(lr.text),
                "cookie_names": list(s.cookies.keys()),
                "snippet": re.sub(r"\s+", " ", lr.text)[:400],
            }
        except Exception as e:
            report["login"] = {"error": str(e)[:200], "action": action, "user_key": user_key, "pass_key": pass_key}

    # search samples
    searches = []
    kw = "绿化养护"
    for u in [
        f"https://s.zhaobiao.cn/search_q_{kw}_pro_320000_p_1.html",
        f"https://jiangsu.zhaobiao.cn/search?keyword={kw}",
        f"https://www.zhaobiao.cn/search.html?wd={kw}&area=320000",
        f"https://s.zhaobiao.cn/?q={kw}&pro=320000",
    ]:
        try:
            r = get(u)
            searches.append(
                {
                    "url": u,
                    "status": r.status_code,
                    "final": str(r.url),
                    "len": len(r.text),
                    "titles": re.findall(r"<a[^>]+>([^<]{8,80})</a>", r.text)[:8],
                    "detail_links": re.findall(r'href=["\']([^"\']*(?:bid|detail|info)[^"\']*)["\']', r.text, re.I)[:8],
                }
            )
        except Exception as e:
            searches.append({"url": u, "error": str(e)[:160]})
    report["searches"] = searches

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:5000])
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
