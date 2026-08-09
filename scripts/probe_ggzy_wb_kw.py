"""WebBridge: navigate search URL with query params, read Vue records."""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.parse
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


def probe_kw(kw: str) -> dict:
    subprocess.run([str(EXE), "start"], check=False)
    time.sleep(2)
    try:
        call("network", {"cmd": "start"})
    except Exception:
        pass

    q = urllib.parse.quote(kw)
    url = f"https://www.ggzy.gov.cn/deal/dealList.html?DEAL_TIME=05&FINDTXT={q}"
    nav = call("navigate", {"url": url, "newTab": False, "group_title": "ggzy-kw"})
    time.sleep(12)

    ev = call(
        "evaluate",
        {
            "code": """(() => {
      const app = document.querySelector('#app');
      const vm = app && app.__vue__;
      let vueData = null;
      if (vm) {
        vueData = {
          myFindTxt: vm.myFindTxt,
          ttlrow: vm.ttlrow,
          ttlpage: vm.ttlpage,
          currentPage: vm.currentPage,
          records: (vm.records || []).slice(0, 15).map(r => ({
            title: r.title || r.noticeName || r.dealTitle || r.NOTICE_NAME || JSON.stringify(r).slice(0,120),
            time: r.publishTime || r.time || r.PUBLISH_TIME || '',
            province: r.province || r.DEAL_PROVINCE_NAME || r.area || '',
            platform: r.platform || r.DEAL_PLATFORM_NAME || '',
            type: r.dealType || r.DEAL_CLASSIFY_NAME || '',
            href: r.url || r.link || r.detailUrl || ''
          }))
        };
      }
      const links = [...document.querySelectorAll('a')].map(a => ({
        t: (a.textContent||'').trim().slice(0,100),
        h: a.href
      })).filter(x => x.t.length > 8);
      const dealLinks = links.filter(x => x.h.includes('information/deal'));
      const text = (document.body.innerText||'').replace(/\\s+/g,' ');
      return JSON.stringify({
        href: location.href,
        title: document.title,
        is405: /405|Not Allowed/.test(document.title + text.slice(0,200)),
        vueData,
        dealLinks: dealLinks.slice(0,20),
        loginHint: /登录|验证码|会员/.test(text),
        captchaHint: /验证码|captcha|滑动/.test(text),
        countHint: (text.match(/共\\s*\\d+\\s*条/)||[])[0] || '',
        textHead: text.slice(0,2000)
      });
    })()"""
        },
    )

    time.sleep(3)
    nets = call("network", {"cmd": "list"})
    try:
        call("network", {"cmd": "stop"})
    except Exception:
        pass

    data = json.loads(ev["data"]["value"]) if ev.get("ok") else {"eval_error": ev}
    hits = []
    nd = nets.get("data")
    entries = nd if isinstance(nd, list) else (nd.get("requests") or nd.get("items") or []) if isinstance(nd, dict) else []
    for e in entries[:300]:
        if not isinstance(e, dict):
            continue
        u = e.get("url") or (e.get("request") or {}).get("url") or ""
        if u:
            hits.append({
                "method": e.get("method") or (e.get("request") or {}).get("method"),
                "status": e.get("status") or (e.get("response") or {}).get("status"),
                "url": u[:600],
            })

    api_hits = [h for h in hits if "information" in h.get("url", "") or "getTrad" in h.get("url", "")]
    records = ((data.get("vueData") or {}).get("records") or [])
    deal_links = data.get("dealLinks") or []
    matched = [x for x in deal_links if kw in x.get("t", "") or any(k in x.get("t", "") for k in ["绿化", "绿植", "租摆", "养护"])]

    result = {
        "keyword": kw,
        "search_url": url,
        "nav_ok": nav.get("ok"),
        "page": data,
        "network_api_hits": api_hits,
        "all_network": hits[:30],
        "result_count_visible": (data.get("vueData") or {}).get("ttlrow") or len(matched) or len(records),
        "sample_titles": [r.get("title") for r in records[:10]] or [x.get("t") for x in matched[:10]],
        "records_sample": records[:10],
        "ok": bool(records or matched) and not data.get("is405"),
    }

    # detail probe
    detail_url = None
    if records and records[0].get("href"):
        detail_url = records[0]["href"]
    elif matched:
        detail_url = matched[0].get("h")
    elif deal_links:
        detail_url = deal_links[0].get("h")

    if detail_url and detail_url.startswith("http"):
        if detail_url.startswith("/"):
            detail_url = "https://www.ggzy.gov.cn" + detail_url
        call("navigate", {"url": detail_url, "newTab": False})
        time.sleep(6)
        det = call(
            "evaluate",
            {
                "code": """(() => {
          const text=(document.body.innerText||'').replace(/\\s+/g,' ');
          const fields={};
          for (const label of ['项目名称','公告标题','采购人','招标人','中标金额','预算金额','成交金额','合同金额','发布时间','公告时间','所在地区','行政区域','项目编号','采购代理机构']) {
            const re=new RegExp(label+'[：:\\s]*([^\\n]{2,120})');
            const m=text.match(re);
            if (m) fields[label]=m[1].trim();
          }
          return JSON.stringify({
            href:location.href, title:document.title,
            loginRequired:/请登录|登录后|会员/.test(text),
            captcha:/验证码|captcha|滑动/.test(text),
            amountVisible:/金额|万元|元|预算|中标价|成交价/.test(text),
            fields,
            textHead:text.slice(0,2000)
          });
        })()"""
            },
        )
        if det.get("ok"):
            result["detail_probe"] = json.loads(det["data"]["value"])
            result["detail_url"] = detail_url

    return result


def main():
    results = []
    for kw in KEYWORDS:
        print("probe", kw)
        results.append(probe_kw(kw))
        time.sleep(5)
    path = OUT / "ggzy_wb_kw.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", path)
    for r in results:
        print(r["keyword"], "ok=", r["ok"], "count=", r["result_count_visible"])


if __name__ == "__main__":
    main()
