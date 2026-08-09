"""Probe 中国采购与招标网: HTTP first, WebBridge if extension connected."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "chinabidding"
OUT.mkdir(parents=True, exist_ok=True)

BASE = "http://127.0.0.1:10086/command"
SESSION = "chinabidding-probe"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
EXE = Path(os.environ["USERPROFILE"]) / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe"

URLS = [
    "https://www.chinabidding.com.cn/",
    "https://www.chinabidding.cn/",
    "https://www.chinabidding.cn/public/yjsc/index.html",
    "https://data.chinabidding.com.cn/",
]


def call(action, args=None, timeout=90):
    body = {"action": action, "args": args or {}, "session": SESSION}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ensure_daemon() -> dict:
    try:
        out = subprocess.check_output([str(EXE), "status"], text=True, timeout=15)
        st = json.loads(out)
    except Exception:
        subprocess.run([str(EXE), "start"], check=False)
        time.sleep(2)
        out = subprocess.check_output([str(EXE), "status"], text=True, timeout=15)
        st = json.loads(out)
    if not st.get("running"):
        subprocess.run([str(EXE), "start"], check=False)
        time.sleep(2)
        out = subprocess.check_output([str(EXE), "status"], text=True, timeout=15)
        st = json.loads(out)
    return st


def http_get(url: str) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
        text = None
        for enc in ("utf-8", "gbk", "gb2312"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = raw.decode("utf-8", "ignore")
        title_m = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
        title = re.sub(r"\s+", " ", unescape(title_m.group(1))).strip() if title_m else ""
        links = []
        for h, inner in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, re.I | re.S)[:200]:
            t = re.sub(r"<[^>]+>", "", inner)
            t = re.sub(r"\s+", " ", unescape(t)).strip()
            if t and re.search(r"招标|采购|中标|搜索|登录|公告|项目", t):
                links.append({"t": t[:50], "h": urllib.parse.urljoin(url, h)[:300]})
            if len(links) >= 30:
                break
        inputs = re.findall(
            r"<input[^>]+>",
            text,
            re.I,
        )[:30]
        forms = re.findall(r"<form[^>]+>", text, re.I)[:10]
        apis = sorted(set(re.findall(r"https?://[^\"'\\s]+(?:api|search|list|ajax)[^\"'\\s]*", text, re.I)))[:40]
        return {
            "ok": True,
            "status": 200,
            "final": url,
            "len": len(text),
            "title": title,
            "links": links[:30],
            "input_tags": [i[:180] for i in inputs],
            "forms": [f[:180] for f in forms],
            "apis": apis,
            "has_login": bool(re.search(r"登录|注册|VIP|会员", text)),
            "has_captcha": bool(re.search(r"验证码|captcha|滑块|geetest", text, re.I)),
        }
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)}


def browser_probe(url: str, new_tab: bool) -> dict:
    item = {"url": url}
    args = {"url": url, "group_title": "采招网探针"}
    if new_tab:
        args["newTab"] = True
    nav = call("navigate", args)
    item["nav"] = nav
    time.sleep(5)
    ev = call(
        "evaluate",
        {
            "code": """(() => {
      const href=location.href, title=document.title;
      const text=(document.body&&document.body.innerText||'').replace(/\\s+/g,' ').slice(0,1600);
      const links=[...document.querySelectorAll('a')].map(a=>({t:(a.textContent||'').trim().slice(0,40),h:a.href}))
        .filter(x=>x.t && /招标|采购|中标|搜索|登录|公告|项目/.test(x.t)).slice(0,35);
      const inputs=[...document.querySelectorAll('input,select,button')].slice(0,35).map(el=>({
        tag:el.tagName,type:el.type||'',name:el.name||'',id:el.id||'',ph:el.placeholder||'',txt:(el.value||el.textContent||'').trim().slice(0,30)
      }));
      return JSON.stringify({href,title,textHead:text.slice(0,900),links,inputs,ready:document.readyState,
        blocked:/无法访问|ERR_|连接已重置|验证码|滑块/.test(href+title+text)});
    })()"""
        },
    )
    if ev.get("ok"):
        item["page"] = json.loads(ev["data"]["value"])
    else:
        item["page"] = ev
    return item


def main():
    report = {"daemon": {}, "http": [], "browser": [], "browser_skipped": None}
    report["daemon"] = ensure_daemon()

    for u in URLS:
        print("[http]", u, flush=True)
        report["http"].append({"url": u, **http_get(u)})

    if not report["daemon"].get("extension_connected"):
        report["browser_skipped"] = "extension not connected; open browser with WebBridge extension"
    else:
        first = True
        for u in URLS:
            print("[browser]", u, flush=True)
            try:
                report["browser"].append(browser_probe(u, new_tab=not first))
            except Exception as e:
                report["browser"].append({"url": u, "error": str(e)})
            first = False

    path = OUT / "probe_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", path)
    print(json.dumps({
        "daemon": report["daemon"],
        "http_ok": [x["url"] for x in report["http"] if x.get("ok")],
        "http_fail": [x.get("url") for x in report["http"] if not x.get("ok")],
        "browser_skipped": report["browser_skipped"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
