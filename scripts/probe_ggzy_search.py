"""WebBridge: keyword search on ggzy dealList with network capture."""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "multi_site"
EXE = Path(os.environ["USERPROFILE"]) / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe"
BASE = "http://127.0.0.1:10086/command"
SESSION = "ggzy-probe"
KEYWORDS = ["绿植租摆", "绿化养护"]


def call(action, args=None, timeout=180):
    body = {"action": action, "args": args or {}, "session": SESSION}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def network_hits(nets):
    hits = []
    data = nets.get("data") if nets.get("ok") else None
    entries = data if isinstance(data, list) else (data.get("requests") or data.get("items") or []) if isinstance(data, dict) else []
    for e in entries[:600]:
        if not isinstance(e, dict):
            continue
        u = e.get("url") or (e.get("request") or {}).get("url") or ""
        if u:
            hits.append({
                "method": e.get("method") or (e.get("request") or {}).get("method"),
                "status": e.get("status") or (e.get("response") or {}).get("status"),
                "url": u[:700],
            })
    return hits


def search_keyword(kw: str) -> dict:
    subprocess.run([str(EXE), "start"], check=False)
    time.sleep(1)
    try:
        call("network", {"cmd": "start"})
    except Exception as e:
        pass

    list_url = "https://www.ggzy.gov.cn/deal/dealList.html"
    nav = call("navigate", {"url": list_url, "newTab": False, "group_title": "ggzy搜索"})
    time.sleep(8)

    # Use page-specific selectors from dealList
    act = call(
        "evaluate",
        {
            "code": f"""(() => {{
      const kw = {json.dumps(kw)};
      // dealList page: keyword input often #keyword or name DEAL_TITLE
      const input = document.querySelector('#keyword, input[name=DEAL_TITLE], input[name=keyword], input[placeholder*=关键词], input[placeholder*=搜索], .search-input input, input[type=text]');
      if (input) {{
        input.focus();
        input.value = kw;
        input.dispatchEvent(new Event('input', {{bubbles:true}}));
        input.dispatchEvent(new Event('change', {{bubbles:true}}));
      }}
      // click 搜索 button
      let clicked = false;
      for (const el of document.querySelectorAll('a,button,span,input')) {{
        const t = ((el.textContent||'')+(el.value||'')).trim();
        if (t === '搜索' || /^搜索$/.test(t)) {{ el.click(); clicked = true; break; }}
      }}
      if (!clicked) {{
        const fn = window.searchDeal || window.doSearch || window.queryDeal || window.search;
        if (typeof fn === 'function') {{ try {{ fn(); clicked = true; }} catch(e) {{}} }}
      }}
      return JSON.stringify({{href:location.href, hasInput:!!input, inputId:input?input.id:'', inputName:input?input.name:'', clicked, title:document.title}});
    }})()"""
        },
    )
    time.sleep(8)

    after = call(
        "evaluate",
        {
            "code": f"""(() => {{
      const kw = {json.dumps(kw)};
      const text = (document.body.innerText||'').replace(/\\s+/g,' ');
      const items = [...document.querySelectorAll('.detail_content, .detail_content a, .list-item, .news-list li, table tr, .deal-list li, a[href*=information/deal]')];
      const links = [...document.querySelectorAll('a')].map(a => ({{
        t: (a.textContent||'').trim().slice(0,100),
        h: a.href
      }})).filter(x => x.t.length > 8);
      const matched = links.filter(x => x.t.includes(kw) || /绿化|绿植|租摆|养护|园林|花卉/.test(x.t));
      const rows = [...document.querySelectorAll('tr, li, .detail_content')].map(el => (el.innerText||'').replace(/\\s+/g,' ').trim()).filter(t => t.length > 15);
      const matchedRows = rows.filter(t => t.includes(kw) || /绿化|绿植|租摆|养护/.test(t));
      const countM = text.match(/共\\s*(\\d+)\\s*条|找到\\s*(\\d+)\\s*条|(\\d+)\\s*条记录/);
      // list field extraction from first rows
      const fieldSample = matchedRows.slice(0,3);
      return JSON.stringify({{
        href: location.href, title: document.title,
        countHint: countM ? countM[0] : '',
        matchedCount: matched.length,
        matchedRowsCount: matchedRows.length,
        matched: matched.slice(0,20),
        matchedRows: matchedRows.slice(0,15),
        fieldSample,
        loginHint: /登录|验证码|会员/.test(text),
        textHead: text.slice(0,1500)
      }});
    }})()"""
        },
    )

    nets = call("network", {"cmd": "list"})
    try:
        call("network", {"cmd": "stop"})
    except Exception:
        pass

    act_data = json.loads(act["data"]["value"]) if act.get("ok") else {"error": act}
    after_data = json.loads(after["data"]["value"]) if after.get("ok") else {"error": after}
    hits = network_hits(nets)

    result = {
        "keyword": kw,
        "nav_ok": nav.get("ok"),
        "act": act_data,
        "after": after_data,
        "network_hits": [h for h in hits if any(k in h["url"].lower() for k in ["deal", "search", "query", "list", "information", "ajax", "api"])][:50],
        "all_network_count": len(hits),
    }
    result["ok"] = (after_data.get("matchedCount", 0) or after_data.get("matchedRowsCount", 0)) > 0
    result["result_count_visible"] = max(after_data.get("matchedCount", 0), after_data.get("matchedRowsCount", 0))
    result["sample_titles"] = [m.get("t") for m in (after_data.get("matched") or [])[:10]]
    result["sample_rows"] = (after_data.get("matchedRows") or [])[:10]
    result["list_url"] = after_data.get("href", list_url)

    # detail probe
    detail_href = None
    for m in (after_data.get("matched") or []):
        if m.get("h") and "information/deal" in m["h"]:
            detail_href = m["h"]
            break
    if not detail_href:
        for m in (after_data.get("matched") or []):
            if m.get("h") and m["h"].startswith("http"):
                detail_href = m["h"]
                break
    if detail_href:
        call("navigate", {"url": detail_href, "newTab": False})
        time.sleep(5)
        det = call(
            "evaluate",
            {
                "code": """(() => {
          const text=(document.body.innerText||'').replace(/\\s+/g,' ');
          const fields={};
          for (const label of ['项目名称','公告标题','采购人','招标人','中标金额','预算金额','成交金额','合同金额','发布时间','公告时间','所在地区','行政区域','项目编号']) {
            const re=new RegExp(label+'[：:\\s]*([^\\n]{2,100})');
            const m=text.match(re);
            if (m) fields[label]=m[1].trim();
          }
          return JSON.stringify({
            href:location.href, title:document.title,
            loginRequired:/请登录|登录后|会员/.test(text),
            captcha:/验证码|captcha|滑动/.test(text),
            amountVisible:/金额|万元|元|预算|中标/.test(text),
            fields,
            textHead:text.slice(0,1500)
          });
        })()"""
            },
        )
        if det.get("ok"):
            result["detail_probe"] = json.loads(det["data"]["value"])
            result["detail_url"] = detail_href

    return result


def main():
    results = []
    for kw in KEYWORDS:
        print("SEARCH", kw)
        results.append(search_keyword(kw))
        time.sleep(3)
    path = OUT / "ggzy_search_probe.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", path)
    for r in results:
        print(r["keyword"], "ok=", r["ok"], "count=", r["result_count_visible"], "net=", len(r["network_hits"]))


if __name__ == "__main__":
    main()
