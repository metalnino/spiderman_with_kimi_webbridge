"""Probe detail page APIs via WebBridge + try HTTP decrypt paths."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "trial" / "detail_probe.json"
BASE = "http://127.0.0.1:10086/command"
SESSION = "detail-probe"
UID = "e5bc6e1262e5469e8589acd7ed691cf2"
URL = f"https://ctbpsp.com/#/bulletinDetail?uuid={UID}&inpvalue=&dataSource=0&tenderAgency="


def call(action, args=None, timeout=90):
    body = {"action": action, "args": args or {}, "session": SESSION}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    out = {"url": URL, "uid": UID}
    try:
        st = urllib.request.urlopen("http://127.0.0.1:10086/", timeout=3)
        out["daemon"] = st.status
    except Exception as e:
        out["daemon_error"] = str(e)

    try:
        call("network", {"cmd": "start"})
    except Exception as e:
        out["network_start_error"] = str(e)

    nav = call("navigate", {"url": URL, "newTab": True, "group_title": "详情探针"})
    out["nav"] = nav
    time.sleep(8)

    page = call(
        "evaluate",
        {
            "code": """(() => {
      const text=(document.body&&document.body.innerText||'').replace(/\\s+/g,' ').slice(0,2500);
      const href=location.href; const title=document.title;
      const money=(text.match(/(预算|金额|限价|报价)[^\\d]{0,8}[￥¥]?[\\d,.]+\\s*万?元?/g)||[]).slice(0,15);
      const links=[...document.querySelectorAll('a')].map(a=>({t:(a.textContent||'').trim().slice(0,40),h:a.href})).filter(x=>x.t&&/原文|来源|官网|查看|下载|附件/.test(x.t)).slice(0,20);
      return JSON.stringify({href,title,textHead:text.slice(0,1500),money,links,ready:document.readyState});
    })()"""
        },
    )
    if page.get("ok"):
        try:
            out["page"] = json.loads(page["data"]["value"])
        except Exception:
            out["page"] = page
    else:
        out["page"] = page

    nets = call("network", {"cmd": "list"})
    call("network", {"cmd": "stop"})
    hits = []
    data = nets.get("data") if nets.get("ok") else None
    entries = []
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = data.get("requests") or data.get("items") or []
        if not entries:
            entries = [v for v in data.values() if isinstance(v, dict) and ("url" in v or "request" in v)]
    for e in entries[:300]:
        if not isinstance(e, dict):
            continue
        u = e.get("url") or (e.get("request") or {}).get("url") or ""
        if any(k in u.lower() for k in ["custominfo", "cutominfo", "bulletin", "detail", "uuid", "api"]):
            hits.append(
                {
                    "method": e.get("method") or (e.get("request") or {}).get("method"),
                    "status": e.get("status") or (e.get("response") or {}).get("status"),
                    "url": u[:500],
                }
            )
    out["network_hits"] = hits[:40]

    # HTTP candidates
    http_try = []
    cands = [
        f"https://custominfo.cebpubservice.com/cutominfoapi/bulletinDetail/{UID}",
        f"https://custominfo.cebpubservice.com/cutominfoapi/getBulletin?uuid={UID}",
        f"https://ctbpsp.com/cutominfoapi/bulletinDetail/{UID}",
        f"https://custominfo.cebpubservice.com/cutominfoapi/bulletin/uuid/{UID}",
    ]
    for u in cands:
        try:
            req = urllib.request.Request(
                u,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://ctbpsp.com/",
                    "Accept": "application/json,text/plain,*/*",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                body = r.read(300)
                http_try.append({"url": u, "status": r.status, "body": body[:200].decode("utf-8", "ignore")})
        except Exception as e:
            http_try.append({"url": u, "error": str(e)})
    out["http_try"] = http_try

    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
