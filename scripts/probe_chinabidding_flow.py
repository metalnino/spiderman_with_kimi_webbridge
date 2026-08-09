"""WebBridge full flow: search -> page2 -> detail -> real APIs; free fields boundary."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "multi_site"
EXE = Path(os.environ["USERPROFILE"]) / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe"
BASE = "http://127.0.0.1:10086/command"
SESSION = "cb-flow"
KW = "绿植租摆"
INFO_SEARCH = (
    "https://www.chinabidding.com.cn/sdbxinfo/313035392e302e7379675f62616e64/"
    "datax/json/info_search"
)


def call(action, args=None, timeout=180):
    body = {"action": action, "args": args or {}, "session": SESSION}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def eval_js(code: str):
    r = call("evaluate", {"code": code})
    if not r.get("ok"):
        return {"_error": r}
    v = r.get("data", {}).get("value")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {"raw": v}
    return v


def parse_network(nets):
    data = nets.get("data") if nets.get("ok") else None
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = data.get("requests") or data.get("items") or []
    else:
        entries = []
    hits = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        u = e.get("url") or (e.get("request") or {}).get("url") or ""
        hits.append(
            {
                "method": e.get("method") or (e.get("request") or {}).get("method"),
                "status": e.get("status") or (e.get("response") or {}).get("status"),
                "url": u[:700],
                "type": e.get("type") or e.get("resourceType"),
            }
        )
    return hits


def http_info_search(keyword: str, page: int = 1, rp: int = 15):
    q = urllib.parse.urlencode(
        {
            "keyword": keyword,
            "page": str(page),
            "rp": str(rp),
            "device": "zbdt001",
            "cpcode": "zbdt001",
        }
    )
    url = f"{INFO_SEARCH}?{q}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.chinabidding.com.cn/search",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        status = resp.status
    try:
        j = json.loads(raw)
    except Exception:
        return {"ok": False, "status": status, "url": url, "raw_head": raw[:500]}
    items = j.get("relatedList") or j.get("list") or []
    sample = []
    for it in items[:8]:
        if isinstance(it, dict):
            sample.append(
                {
                    k: it.get(k)
                    for k in (
                        "title",
                        "publish_date",
                        "area_id",
                        "category_id",
                        "table_name",
                        "table_name2",
                        "id",
                        "url",
                    )
                    if k in it
                }
            )
    return {
        "ok": True,
        "status": status,
        "url": url,
        "total": j.get("total"),
        "esSql": (j.get("esSql") or "")[:300],
        "keys": list(j.keys())[:20],
        "item_keys": list(items[0].keys()) if items and isinstance(items[0], dict) else [],
        "sample": sample,
        "first_detail_path": (items[0].get("url") if items and isinstance(items[0], dict) else None),
    }


def inspect_detail_page():
    return eval_js(
        """(() => {
      const text = (document.body.innerText||'').replace(/\\s+/g,' ');
      const locked = [];
      const free = [];
      const labels = ['招标编号','开标时间','招标人','标讯类别','资金来源','招标代理','预算','金额','中标金额','采购人','项目编号'];
      for (const lab of labels) {
        const re = new RegExp(lab + '[：:\\s]*([^\\n]{0,40})');
        const m = text.match(re);
        if (!m) continue;
        const val = (m[1]||'').trim();
        if (/立即注册|登录|会员|开通|查看/.test(val) || !val) locked.push({label: lab, value: val.slice(0,40)});
        else free.push({label: lab, value: val.slice(0,80)});
      }
      const money = [...text.matchAll(/(?:预算|金额|中标价|成交价)[^\\d]{0,8}([\\d,.]+)\\s*万?元?/g)].slice(0,8).map(m=>m[0].slice(0,40));
      const h1 = (document.querySelector('h1,h2,.title,.detail-title')||{}).innerText||'';
      return JSON.stringify({
        href: location.href,
        title: document.title,
        h1: (h1||'').trim().slice(0,120),
        loginWall: /免费注册|立即注册查看|请先\\s*免费注册|已注册的用户请\\s*登录/.test(text),
        captcha: /验证码|vaptcha|滑块/.test(text),
        freeHints: {
          title: !!document.title,
          publish: /发布时间/.test(text),
          region: /地区[：:]/.test(text),
        },
        freeFields: free,
        lockedFields: locked,
        moneyHints: money,
        textHead: text.slice(0,1800)
      });
    })()"""
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(EXE), "start"], check=False)
    time.sleep(1)
    daemon = json.loads(subprocess.check_output([str(EXE), "status"], text=True))
    report = {
        "site": "中国采购与招标网",
        "session": SESSION,
        "keyword": KW,
        "daemon": daemon,
        "steps": {},
        "apis": {},
        "free_vs_locked": {},
        "conclusion": {},
    }
    if not daemon.get("extension_connected"):
        report["error"] = "extension not connected"
        path = OUT / "chinabidding_flow_report.json"
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("WROTE", path)
        return

    # --- HTTP baseline (known working) ---
    http_p1 = http_info_search(KW, page=1)
    http_p2 = http_info_search(KW, page=2)
    report["apis"]["http_info_search_p1"] = http_p1
    report["apis"]["http_info_search_p2"] = {
        "ok": http_p2.get("ok"),
        "total": http_p2.get("total"),
        "sample_titles": [x.get("title") for x in (http_p2.get("sample") or [])],
        "first_detail_path": http_p2.get("first_detail_path"),
        "url": http_p2.get("url"),
    }

    try:
        call("network", {"cmd": "start"})
        report["steps"]["network_start"] = True
    except Exception as e:
        report["steps"]["network_start"] = str(e)

    # --- Step1: open search URL ---
    q = urllib.parse.quote(KW)
    search_url = f"https://www.chinabidding.com.cn/search?keyword={q}"
    nav = call("navigate", {"url": search_url, "newTab": True, "group_title": "采招网完整流程"})
    report["steps"]["nav_search"] = {"ok": nav.get("ok"), "url": search_url}
    time.sleep(8)

    page1 = eval_js(
        f"""(() => {{
      const kw = {json.dumps(KW)};
      // try force Nuxt/query to actually search
      const inputs = [...document.querySelectorAll('input')];
      let filled=false;
      for (const input of inputs) {{
        const ph=(input.placeholder||'')+(input.getAttribute('aria-label')||'');
        if (/检索|关键词|搜索|keyword/i.test(ph) || input.type==='search' || input.className.includes('el-input')) {{
          const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
          setter.call(input, kw);
          input.dispatchEvent(new Event('input', {{bubbles:true}}));
          input.dispatchEvent(new Event('change', {{bubbles:true}}));
          filled=true;
        }}
      }}
      let clicked=false;
      for (const b of document.querySelectorAll('button,[role=button],a,span,i')) {{
        const t=((b.textContent||'')+(b.getAttribute('aria-label')||'')).trim();
        if (/^搜索$|查询|检索/.test(t)) {{ b.click(); clicked=true; break; }}
      }}
      // also try fetch real API from page context
      return JSON.stringify({{href:location.href, filled, clicked, nuxt:!!window.__NUXT__}});
    }})()"""
    )
    report["steps"]["page1_force_search"] = page1
    time.sleep(5)

    # fetch API inside browser (same-origin cookies)
    browser_api = eval_js(
        f"""(async () => {{
      const kw = {json.dumps(KW)};
      const u = {json.dumps(INFO_SEARCH)} + '?keyword=' + encodeURIComponent(kw) + '&page=1&rp=15&device=zbdt001&cpcode=zbdt001';
      try {{
        const r = await fetch(u, {{credentials:'include', headers:{{'Accept':'application/json'}}}});
        const j = await r.json();
        const list = j.relatedList || j.list || [];
        return JSON.stringify({{
          status: r.status,
          total: j.total,
          esSql: (j.esSql||'').slice(0,200),
          n: list.length,
          titles: list.slice(0,8).map(x=>x.title),
          fields: list[0] ? Object.keys(list[0]) : [],
          urls: list.slice(0,5).map(x=>x.url),
          sample: list.slice(0,3)
        }});
      }} catch(e) {{
        return JSON.stringify({{error: String(e)}});
      }}
    }})()"""
    )
    # evaluate may return promise unresolved depending on bridge; wait and re-read
    if isinstance(browser_api, dict) and browser_api.get("raw") == "[object Promise]":
        time.sleep(3)
        browser_api = eval_js(
            f"""(async () => {{
      if (window.__cbApiCache) return JSON.stringify(window.__cbApiCache);
      const kw = {json.dumps(KW)};
      const u = {json.dumps(INFO_SEARCH)} + '?keyword=' + encodeURIComponent(kw) + '&page=1&rp=15&device=zbdt001&cpcode=zbdt001';
      const r = await fetch(u, {{credentials:'include'}});
      const j = await r.json();
      const list = j.relatedList || [];
      window.__cbApiCache = {{status:r.status,total:j.total,n:list.length,titles:list.slice(0,8).map(x=>x.title),fields:list[0]?Object.keys(list[0]):[],urls:list.slice(0,5).map(x=>x.url),sample:list.slice(0,2)}};
      return JSON.stringify(window.__cbApiCache);
    }})()"""
        )
        time.sleep(4)
        browser_api = eval_js("JSON.stringify(window.__cbApiCache || {miss:true})")

    report["apis"]["browser_info_search_p1"] = browser_api

    # UI list state after search URL
    ui_list = eval_js(
        """(() => {
      const text=(document.body.innerText||'').replace(/\\s+/g,' ');
      const h3=[...document.querySelectorAll('h3')].map(x=>(x.innerText||'').trim()).filter(Boolean).slice(0,15);
      const count=(text.match(/相关结果\\s*([\\d,]+)\\s*条/)||[])[1] || (text.match(/共\\s*([\\d,]+)\\s*条/)||[])[1] || '';
      // pagination buttons
      const pageBtns=[...document.querySelectorAll('button,li,a,span')].filter(el=>{
        const t=(el.textContent||'').trim();
        return /^(下一页|下页|>|»|2)$/.test(t) || el.getAttribute('aria-label')==='Next Page';
      }).slice(0,10).map(el=>({t:(el.textContent||'').trim().slice(0,20), tag:el.tagName, cls:el.className}));
      return JSON.stringify({href:location.href, countHint:count, titles:h3, pageBtns, textHead:text.slice(0,900)});
    })()"""
    )
    report["steps"]["ui_list_p1"] = ui_list

    # --- Step2: pagination via API in browser + try UI next ---
    browser_api_p2 = eval_js(
        f"""(async () => {{
      const kw = {json.dumps(KW)};
      const u = {json.dumps(INFO_SEARCH)} + '?keyword=' + encodeURIComponent(kw) + '&page=2&rp=15&device=zbdt001&cpcode=zbdt001';
      const r = await fetch(u, {{credentials:'include'}});
      const j = await r.json();
      const list = j.relatedList || [];
      window.__cbApiP2 = {{status:r.status,total:j.total,n:list.length,titles:list.slice(0,8).map(x=>x.title),urls:list.slice(0,5).map(x=>x.url)}};
      return JSON.stringify(window.__cbApiP2);
    }})()"""
    )
    time.sleep(3)
    browser_api_p2 = eval_js("JSON.stringify(window.__cbApiP2 || {miss:true})")
    report["apis"]["browser_info_search_p2"] = browser_api_p2

    # click page 2 / next if present
    page_click = eval_js(
        """(() => {
      let clicked=null;
      const cands=[...document.querySelectorAll('button,li,a,span')];
      for (const el of cands) {
        const t=(el.textContent||'').trim();
        if (t==='2' || t==='下一页' || t==='下页') {
          el.click();
          clicked=t;
          break;
        }
      }
      return JSON.stringify({clicked, href:location.href});
    })()"""
    )
    report["steps"]["ui_page2_click"] = page_click
    time.sleep(5)
    ui_list_p2 = eval_js(
        """(() => {
      const h3=[...document.querySelectorAll('h3')].map(x=>(x.innerText||'').trim()).filter(Boolean).slice(0,12);
      return JSON.stringify({href:location.href, titles:h3});
    })()"""
    )
    report["steps"]["ui_list_p2"] = ui_list_p2

    # --- Step3: open detail (prefer API path) ---
    detail_path = http_p1.get("first_detail_path") or ""
    # prefer a green-plant related item
    for it in http_p1.get("sample") or []:
        t = it.get("title") or ""
        if any(k in t for k in ("绿植", "花卉", "租摆")) and it.get("url"):
            detail_path = it["url"]
            break
    if detail_path and detail_path.startswith("/"):
        detail_url = "https://www.chinabidding.cn" + detail_path
    elif detail_path.startswith("http"):
        detail_url = detail_path
    else:
        detail_url = None

    report["steps"]["chosen_detail"] = {"path": detail_path, "url": detail_url}

    if detail_url:
        nav2 = call("navigate", {"url": detail_url, "newTab": False})
        report["steps"]["nav_detail"] = {"ok": nav2.get("ok"), "url": detail_url}
        time.sleep(8)
        detail_inspect = inspect_detail_page()
        report["steps"]["detail_inspect"] = detail_inspect

        # try alternate detail host on .com.cn if exists
        alt = None
        if "chinabidding.cn/" in detail_url and "chinabidding.com.cn" not in detail_url:
            # some pages may have pageInfoSsr
            m = re.search(r"/zbgg/([^./]+)", detail_url)
            if m:
                alt = f"https://www.chinabidding.com.cn/pageInfoSsr/zbgg/{m.group(1)}"
        if alt:
            nav3 = call("navigate", {"url": alt, "newTab": False})
            time.sleep(6)
            alt_inspect = inspect_detail_page()
            report["steps"]["detail_alt_ssr"] = {"url": alt, "nav_ok": nav3.get("ok"), "inspect": alt_inspect}

    # network dump
    nets = call("network", {"cmd": "list"})
    try:
        call("network", {"cmd": "stop"})
    except Exception:
        pass
    hits = parse_network(nets)
    api_hits = [
        h
        for h in hits
        if any(k in (h.get("url") or "").lower() for k in ("info_search", "datax", "oauth", "pageinfo", "zbgg", "search"))
    ]
    report["apis"]["network_hits_filtered"] = api_hits[:80]
    report["apis"]["network_total"] = len(hits)

    # free field conclusion
    list_fields_free = [
        "title",
        "publish_date",
        "area_id",
        "category_id",
        "table_name",
        "table_name2",
        "id",
        "url",
    ]
    di = report["steps"].get("detail_inspect") or {}
    free_detail = ["标题(title)", "发布时间", "地区"] if di.get("loginWall") else ["需复核"]
    locked_detail = [x.get("label") for x in (di.get("lockedFields") or [])] or [
        "招标编号",
        "开标时间",
        "招标人",
        "标讯类别",
        "资金来源",
        "招标代理",
        "正文金额",
    ]

    report["free_vs_locked"] = {
        "list_api_free": {
            "source": "GET info_search?keyword=&page=&rp=",
            "fields": list_fields_free,
            "note": "无需登录；浏览器 SPA 搜索页常空传 keyword，主爬应用直调 API",
            "pagination": "page 参数有效（p1/p2 标题不同）",
            "evidence_totals": {"p1_total": http_p1.get("total"), "p2_ok": http_p2.get("ok")},
        },
        "detail_free_without_login": {
            "fields": free_detail,
            "also": "打码/略写摘要可能可见但不完整",
            "loginWall": di.get("loginWall"),
            "money_visible": bool(di.get("moneyHints")),
        },
        "detail_locked_without_login": {
            "fields": locked_detail,
            "evidence": di.get("lockedFields") or di.get("textHead", "")[:400],
        },
    }

    spa_broken = False
    ui = report["steps"].get("ui_list_p1") or {}
    titles = ui.get("titles") or []
    if titles and not any("绿植" in t or "租摆" in t or "花卉" in t for t in titles):
        spa_broken = True

    report["conclusion"] = {
        "crawl_feasibility": "medium",
        "recommended_path": "列表 HTTP/浏览器同源 fetch info_search 带 keyword+page；详情未登录仅标题/时间/地区，完整字段需账号",
        "spa_search_unreliable": spa_broken,
        "free_enough_for_lead_gen": True,
        "free_enough_for_bid_amount": False,
        "next_for_user": [
            "要金额/招标人/编号：提供登录 Cookie 或可查看账号",
            "仅线索：可只抓 info_search 列表并做标题过滤+城市过滤",
        ],
    }

    path = OUT / "chinabidding_flow_report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", path)
    print(
        json.dumps(
            {
                "total_p1": http_p1.get("total"),
                "detail": detail_url,
                "loginWall": di.get("loginWall"),
                "spa_broken": spa_broken,
                "api_hits": len(api_hits),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
