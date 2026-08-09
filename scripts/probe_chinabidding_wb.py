"""WebBridge: open chinabidding search, type keyword, capture APIs."""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "chinabidding"
EXE = Path(os.environ["USERPROFILE"]) / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe"
BASE = "http://127.0.0.1:10086/command"
SESSION = "chinabidding-probe2"
KW = "绿化养护"


def call(action, args=None, timeout=120):
    body = {"action": action, "args": args or {}, "session": SESSION}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ensure():
    subprocess.run([str(EXE), "start"], check=False)
    time.sleep(2)
    st = json.loads(subprocess.check_output([str(EXE), "status"], text=True))
    return st


def main():
    st = ensure()
    report = {"daemon": st, "steps": []}
    if not st.get("extension_connected"):
        report["error"] = "extension not connected"
        (OUT / "wb_search_probe.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return

    try:
        call("network", {"cmd": "start"})
    except Exception as e:
        report["network_start"] = str(e)

    url = f"https://www.chinabidding.com.cn/search?keyword={KW}"
    nav = call("navigate", {"url": url, "newTab": True, "group_title": "采招网搜索探针"})
    report["nav"] = nav
    time.sleep(8)

    snap = call("snapshot", {})
    report["snapshot_ok"] = bool(snap.get("ok"))
    if snap.get("ok"):
        # keep compact tree names
        tree = json.dumps(snap["data"].get("tree"), ensure_ascii=False)
        report["snapshot_head"] = tree[:4000]
        report["page_url"] = snap["data"].get("url")
        report["page_title"] = snap["data"].get("title")

    # try fill search box and press search via evaluate
    act = call(
        "evaluate",
        {
            "code": f"""(() => {{
      const kw = {json.dumps(KW)};
      const input = document.querySelector('input[placeholder*=\"检索\"], input[placeholder*=\"关键词\"], input.el-input__inner, input[type=text], input[type=search]');
      if (input) {{
        input.focus();
        input.value = kw;
        input.dispatchEvent(new Event('input', {{bubbles:true}}));
        input.dispatchEvent(new Event('change', {{bubbles:true}}));
      }}
      // click search button
      let clicked=false;
      const btns=[...document.querySelectorAll('button,a,span,i')];
      for (const b of btns) {{
        const t=((b.textContent||'')+(b.getAttribute('aria-label')||'')).trim();
        if (/搜索|查询|检索/.test(t)) {{ b.click(); clicked=true; break; }}
      }}
      // wait-ish: collect visible result texts
      const rows=[...document.querySelectorAll('.el-table__row, .result-item, .list-item, li, tr')].slice(0,40).map(el=>(el.innerText||'').replace(/\\s+/g,' ').trim().slice(0,120)).filter(t=>t.length>10);
      const text=(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,1500);
      return JSON.stringify({{hasInput:!!input, clicked, rows:rows.slice(0,20), textHead:text.slice(0,900), href:location.href}});
    }})()"""
        },
    )
    report["act"] = json.loads(act["data"]["value"]) if act.get("ok") else act
    time.sleep(5)

    after = call(
        "evaluate",
        {
            "code": """(() => {
      const rows=[...document.querySelectorAll('a')].map(a=>({t:(a.textContent||'').trim().slice(0,80),h:a.href}))
        .filter(x=>x.t.length>8 && /绿化|养护|租摆|园林|招标|采购|公告/.test(x.t)).slice(0,30);
      const text=(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,1800);
      const login=/登录|会员|VIP|开通|权限/.test(text);
      return JSON.stringify({href:location.href,title:document.title,loginHint:login,rows,textHead:text.slice(0,1200)});
    })()"""
        },
    )
    report["after"] = json.loads(after["data"]["value"]) if after.get("ok") else after

    nets = call("network", {"cmd": "list"})
    try:
        call("network", {"cmd": "stop"})
    except Exception:
        pass
    hits = []
    data = nets.get("data") if nets.get("ok") else None
    entries = []
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = data.get("requests") or data.get("items") or []
        if not entries:
            entries = [v for v in data.values() if isinstance(v, dict) and ("url" in v or "request" in v)]
    for e in entries[:400]:
        if not isinstance(e, dict):
            continue
        u = e.get("url") or (e.get("request") or {}).get("url") or ""
        if any(k in u.lower() for k in ["search", "api", "list", "query", "bid", "ajax", "page"]):
            hits.append({
                "method": e.get("method") or (e.get("request") or {}).get("method"),
                "status": e.get("status") or (e.get("response") or {}).get("status"),
                "url": u[:500],
            })
    report["network_hits"] = hits[:60]

    path = OUT / "wb_search_probe.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", path)
    print(json.dumps({
        "extension": st.get("extension_connected"),
        "rows": len((report.get("after") or {}).get("rows") or []),
        "network": len(hits),
        "loginHint": (report.get("after") or {}).get("loginHint"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
