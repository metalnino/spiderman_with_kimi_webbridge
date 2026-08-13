"""Probe jiangsu.zhaobiao.cn login + search (no secrets printed)."""
from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import load_env  # noqa: E402

HOME = "http://jiangsu.zhaobiao.cn"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
OUT = ROOT / "data" / "web" / "jiangsu_zhaobiao_probe.json"


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.forms = []
        self._cur = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "form":
            self._cur = {"action": a.get("action"), "method": (a.get("method") or "get").lower(), "inputs": {}}
            self.forms.append(self._cur)
        if tag == "input" and self._cur is not None:
            name = a.get("name")
            if name:
                self._cur["inputs"][name] = a.get("value") or ""


def main() -> None:
    env = load_env()
    user = env.get("JIANGSU_ZHAOBIAO_USER") or env.get("ZHAOBIAO_JS_USER")
    pwd = env.get("JIANGSU_ZHAOBIAO_PASS") or env.get("ZHAOBIAO_JS_PASS")
    report: dict = {"home": HOME, "has_user": bool(user), "has_pass": bool(pwd)}
    if not user or not pwd:
        report["error"] = "missing JIANGSU_ZHAOBIAO_USER/PASS in .env"
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    cj = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    def fetch(url: str, data: bytes | None = None, headers: dict | None = None) -> tuple[int, str, str]:
        hdrs = {"User-Agent": UA, "Accept": "text/html,application/json,*/*"}
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data else "GET")
        with opener.open(req, timeout=30) as resp:
            raw = resp.read()
            text = raw.decode("utf-8", "ignore")
            if not text or "\ufffd" in text[:200]:
                text = raw.decode("gbk", "ignore")
            return resp.status, text, resp.geturl()

    st, home_html, final = fetch(HOME)
    report["home_status"] = st
    report["home_final"] = final
    report["home_len"] = len(home_html)
    report["home_title"] = (re.search(r"<title[^>]*>(.*?)</title>", home_html, re.I | re.S) or [None, ""])[1][:80]

    # find login links
    links = re.findall(r'href=["\']([^"\']*(?:login|user|member|signin)[^"\']*)["\']', home_html, re.I)
    report["loginish_links"] = list(dict.fromkeys(links))[:20]

    # try common login pages
    candidates = [
        HOME + "/",
        HOME + "/login",
        HOME + "/user/login",
        HOME + "/member/login",
        "https://jiangsu.zhaobiao.cn/login",
        "http://www.zhaobiao.cn/login.html",
        "https://www.zhaobiao.cn/login.html",
    ]
    for u in list(report["loginish_links"]):
        if u.startswith("//"):
            candidates.append("http:" + u)
        elif u.startswith("/"):
            candidates.append(HOME + u)
        elif u.startswith("http"):
            candidates.append(u)

    login_pages = []
    for u in dict.fromkeys(candidates):
        try:
            st, html, final = fetch(u)
        except Exception as e:
            login_pages.append({"url": u, "error": str(e)[:120]})
            continue
        p = FormParser()
        try:
            p.feed(html)
        except Exception:
            pass
        forms = []
        for f in p.forms:
            keys = list(f["inputs"].keys())
            if any(re.search(r"user|name|account|mobile|phone|email", k, re.I) for k in keys) and any(
                re.search(r"pass|pwd", k, re.I) for k in keys
            ):
                forms.append({"action": f["action"], "method": f["method"], "fields": keys})
        login_pages.append(
            {
                "url": u,
                "final": final,
                "status": st,
                "len": len(html),
                "forms": forms,
                "has_password_input": "password" in html.lower() or "type=\"password\"" in html.lower(),
            }
        )
    report["login_pages"] = login_pages

    # pick first form and attempt login
    target = next((x for x in login_pages if x.get("forms")), None)
    if target:
        st, html, final = fetch(target["url"])
        p = FormParser()
        p.feed(html)
        form = None
        for f in p.forms:
            keys = list(f["inputs"].keys())
            if any(re.search(r"pass|pwd", k, re.I) for k in keys):
                form = f
                break
        if form:
            payload = dict(form["inputs"])
            for k in list(payload):
                if re.search(r"user|name|account|mobile|phone|email|login", k, re.I) and not re.search(
                    r"pass|pwd", k, re.I
                ):
                    payload[k] = user
                if re.search(r"pass|pwd", k, re.I):
                    payload[k] = pwd
            action = form["action"] or final
            if action.startswith("/"):
                action = urllib.parse.urljoin(final, action)
            elif not action.startswith("http"):
                action = urllib.parse.urljoin(final, action)
            body = urllib.parse.urlencode(payload).encode("utf-8")
            try:
                st2, html2, final2 = fetch(
                    action,
                    data=body,
                    headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": final},
                )
                report["login_attempt"] = {
                    "action": action,
                    "status": st2,
                    "final": final2,
                    "len": len(html2),
                    "snippet": re.sub(r"\s+", " ", html2)[:300],
                    "cookie_names": [c.name for c in cj],
                    "looks_ok": not re.search(r"密码错误|用户不存在|验证码|login", html2[:2000], re.I)
                    or bool([c.name for c in cj]),
                }
            except Exception as e:
                report["login_attempt"] = {"error": str(e)[:200], "action": action}

    # search probes after cookies
    searches = []
    kw = "绿化养护"
    for url in [
        f"{HOME}/search?keyword={urllib.parse.quote(kw)}",
        f"{HOME}/search.html?keyword={urllib.parse.quote(kw)}",
        f"http://jiangsu.zhaobiao.cn/search/search.do?keyword={urllib.parse.quote(kw)}",
        f"https://www.zhaobiao.cn/search?keyword={urllib.parse.quote(kw)}&area=jiangsu",
    ]:
        try:
            st, html, final = fetch(url)
            searches.append(
                {
                    "url": url,
                    "status": st,
                    "final": final,
                    "len": len(html),
                    "has_kw": kw in html,
                    "links": re.findall(r'href=["\']([^"\']+detail[^"\']*)["\']', html, re.I)[:5],
                }
            )
        except Exception as e:
            searches.append({"url": url, "error": str(e)[:160]})
    report["searches"] = searches

    # expose interesting network endpoints in homepage scripts
    apis = re.findall(r'["\'](/[^"\']*(?:search|login|api|list)[^"\']*)["\']', home_html, re.I)
    report["apiish"] = list(dict.fromkeys(apis))[:40]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    # print without secrets
    print(json.dumps({k: v for k, v in report.items()}, ensure_ascii=False, indent=2)[:4000])
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
