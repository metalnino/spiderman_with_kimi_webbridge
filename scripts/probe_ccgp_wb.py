"""WebBridge probe: 中国政府采购网 ccgp.gov.cn"""
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
OUT = ROOT / "data" / "multi_site"
OUT.mkdir(parents=True, exist_ok=True)
REPORT = OUT / "ccgp_report.json"

EXE = Path(os.environ["USERPROFILE"]) / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe"
BASE = "http://127.0.0.1:10086/command"
SESSION = "ccgp-probe"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
KEYWORDS = ["绿植租摆", "绿化养护", "室内绿化"]
HOSTS = ["www.ccgp.gov.cn", "search.ccgp.gov.cn"]


def call(action, args=None, timeout=120):
    body = {"action": action, "args": args or {}, "session": SESSION}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def ensure():
    subprocess.run([str(EXE), "start"], check=False)
    time.sleep(2)
    return json.loads(subprocess.check_output([str(EXE), "status"], text=True))


def http_get(url: str) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            final = r.geturl()
            status = r.status
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
        for h, inner in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, re.I | re.S):
            t = re.sub(r"<[^>]+>", "", inner)
            t = re.sub(r"\s+", " ", unescape(t)).strip()
            if t and re.search(r"搜索|公告|采购|查询|search", t, re.I):
                links.append({"t": t[:60], "h": urllib.parse.urljoin(url, h)[:400]})
            if len(links) >= 40:
                break
        inputs = re.findall(r"<input[^>]+>", text, re.I)[:15]
        has_login = bool(re.search(r"登录|login", text, re.I))
        has_captcha = bool(re.search(r"验证码|captcha|滑动", text, re.I))
        return {
            "url": url,
            "ok": True,
            "status": status,
            "final": final,
            "len": len(text),
            "title": title,
            "links": links,
            "input_tags": inputs[:8],
            "has_login": has_login,
            "has_captcha": has_captcha,
        }
    except Exception as e:
        return {"url": url, "ok": False, "error": str(e)}


def eval_json(code: str) -> dict:
    r = call("evaluate", {"code": code})
    if r.get("ok") and r.get("data", {}).get("value"):
        try:
            return json.loads(r["data"]["value"])
        except json.JSONDecodeError:
            return {"raw": r["data"]["value"][:2000]}
    return {"error": r}


def probe_home():
    nav = call("navigate", {"url": "https://www.ccgp.gov.cn/", "newTab": True, "group_title": "CCGP探针"})
    time.sleep(5)
    home = eval_json("""(() => {
      const links=[...document.querySelectorAll('a')].map(a=>({
        t:(a.textContent||'').trim().slice(0,80),
        h:a.href
      })).filter(x=>/搜索|公告|采购|查询|search|信息公告/i.test(x.t+x.h)).slice(0,35);
      const inputs=[...document.querySelectorAll('input,select')].map(el=>({
        tag:el.tagName, type:el.type||'', name:el.name||'', id:el.id||'', ph:el.placeholder||''
      })).slice(0,12);
      const text=(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,2000);
      return JSON.stringify({
        href:location.href, title:document.title, links, inputs,
        loginHint:/登录|会员|注册/.test(text),
        captchaHint:/验证码|滑动验证/.test(text),
        textHead:text.slice(0,900)
      });
    })()""")
    return nav, home


def search_keyword(kw: str):
    enc = urllib.parse.quote(kw)
    candidates = [
        f"https://search.ccgp.gov.cn/bxsearch?searchtype=1&page_index=1&bidSort=0&buyerName=&projectId=&pinMu=0&bidType=0&dbselect=bidx&kw={enc}",
        f"https://www.ccgp.gov.cn/cggg/zygg/",
        f"https://www.ccgp.gov.cn/",
    ]
    url = candidates[0]
    nav = call("navigate", {"url": url, "newTab": False})
    time.sleep(6)
    # if search page, try fill kw
    act = eval_json(f"""(() => {{
      const kw = {json.dumps(kw)};
      let input = document.querySelector('input[name=kw], input#kw, input[placeholder*=关键词], input[type=text]');
      if (input && !location.href.includes('kw=')) {{
        input.value = kw;
        input.dispatchEvent(new Event('input', {{bubbles:true}}));
        const btn = [...document.querySelectorAll('button,a,input[type=button],input[type=submit]')]
          .find(b => /搜索|查询|检索/.test((b.textContent||b.value||'')));
        if (btn) btn.click();
      }}
      return 'ok';
    }})()""")
    time.sleep(5)
    page = eval_json("""(() => {
      const rows=[...document.querySelectorAll('ul.vT-srch-result-list-bid li, .vT-srch-result-list-bid li, table tr, .list li, .search-result li, a')];
      const items=[];
      for (const el of rows) {
        const a = el.tagName==='A' ? el : el.querySelector('a');
        if (!a) continue;
        const t=(a.textContent||'').trim();
        if (t.length<8) continue;
        const rowText=(el.innerText||'').replace(/\\s+/g,' ').trim().slice(0,200);
        items.push({title:t.slice(0,120), href:a.href, row:rowText});
        if (items.length>=15) break;
      }
      const text=(document.body.innerText||'').replace(/\\s+/g,' ');
      const hasAmount=/\\d+(\\.\\d+)?\\s*(万元|元)/.test(text);
      const fields={};
      if (/发布时间|公告时间/.test(text)) fields.time=true;
      if (/采购人|招标人|采购单位/.test(text)) fields.buyer=true;
      if (/地区|行政区域|省份/.test(text)) fields.region=true;
      if (hasAmount) fields.amount_in_list=true;
      return JSON.stringify({
        href:location.href, title:document.title,
        result_count: items.length,
        items: items.slice(0,12),
        list_fields: fields,
        loginHint:/登录|会员/.test(text),
        captchaHint:/验证码|滑动/.test(text),
        emptyHint:/没有找到|暂无|0条/.test(text),
        textHead:text.slice(0,1200)
      });
    })()""")
    return {"keyword": kw, "nav": nav.get("ok"), "url": page.get("href"), "page": page}


def probe_detail(detail_url: str):
    if not detail_url or "ccgp" not in detail_url:
        return {"skipped": True}
    nav = call("navigate", {"url": detail_url, "newTab": False})
    time.sleep(5)
    detail = eval_json("""(() => {
      const text=(document.body.innerText||'').replace(/\\s+/g,' ');
      const fields={};
      const patterns={
        title:document.title,
        publish_time:/发布时间[:：]\\s*([\\d\\-年月日 :]+)/.exec(text),
        buyer:/采购人[:：]\\s*([^\\s]{2,40})/.exec(text),
        agent:/代理机构[:：]\\s*([^\\s]{2,40})/.exec(text),
        amount:/(?:预算|金额|中标|成交金额)[:：]?\\s*([\\d,.]+\\s*(?:万元|元))/.exec(text),
        region:/(?:行政区域|地区)[:：]\\s*([^\\s]{2,20})/.exec(text),
      };
      for (const [k,v] of Object.entries(patterns)) {
        if (Array.isArray(v) && v[1]) fields[k]=v[1].slice(0,80);
        else if (typeof v==='string') fields[k]=v.slice(0,120);
      }
      return JSON.stringify({
        href:location.href,
        reachable: text.length>200,
        loginHint:/登录|会员|权限/.test(text),
        captchaHint:/验证码|滑动/.test(text),
        fields,
        textHead:text.slice(0,1500)
      });
    })()""")
    return {"nav": nav.get("ok"), "detail": detail}


def collect_network():
    nets = call("network", {"cmd": "list"})
    hits = []
    data = nets.get("data") if nets.get("ok") else None
    entries = []
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = data.get("requests") or data.get("items") or []
    for e in entries[:500]:
        if not isinstance(e, dict):
            continue
        u = e.get("url") or (e.get("request") or {}).get("url") or ""
        if any(k in u.lower() for k in ["search", "ccgp", "bxsearch", "cggg", "api", "query", "list", "ajax"]):
            hits.append({
                "method": e.get("method") or (e.get("request") or {}).get("method"),
                "status": e.get("status") or (e.get("response") or {}).get("status"),
                "url": u[:500],
            })
    return hits[:80]


def build_report(st, http_results, home, keyword_tests, detail_probe, network_hits):
    search_entry = {
        "primary": "https://search.ccgp.gov.cn/bxsearch",
        "params": "searchtype=1&dbselect=bidx&kw=关键词&page_index=1",
        "home_links": (home or {}).get("links", [])[:15],
        "home_inputs": (home or {}).get("inputs", []),
    }
    list_fields = []
    for kt in keyword_tests:
        lf = (kt.get("page") or {}).get("list_fields") or {}
        if lf:
            list_fields = list(set(list_fields) | set(lf.keys()))
    detail_fields = list((detail_probe.get("detail") or {}).get("fields", {}).keys())

    blockers = []
    if any((home or {}).get(k) for k in ("loginHint", "captchaHint")):
        if home.get("loginHint"):
            blockers.append({"level": "low", "type": "login_hint_on_home", "note": "首页有登录入口，非强制"})
        if home.get("captchaHint"):
            blockers.append({"level": "medium", "type": "captcha_hint", "note": "可能存在验证码"})
    for kt in keyword_tests:
        p = kt.get("page") or {}
        if p.get("captchaHint"):
            blockers.append({"level": "medium", "type": "captcha_on_search", "keyword": kt["keyword"]})
        if p.get("loginHint"):
            blockers.append({"level": "low", "type": "login_on_search", "keyword": kt["keyword"]})

    http_ok = any(h.get("ok") for h in http_results)
    any_results = any((kt.get("page") or {}).get("result_count", 0) > 0 for kt in keyword_tests)
    detail_ok = (detail_probe.get("detail") or {}).get("reachable", False)

    amount_in_list = any(
        (kt.get("page") or {}).get("list_fields", {}).get("amount_in_list")
        for kt in keyword_tests
    )
    amount_in_detail = "amount" in detail_fields

    if http_ok and any_results and detail_ok:
        feasibility = "high"
        path = "HTTP/浏览器直访 search.ccgp.gov.cn 关键词列表，再抓详情页 HTML"
    elif http_ok and any_results:
        feasibility = "medium-high"
        path = "列表可抓；详情需再验证字段解析"
    elif http_ok:
        feasibility = "medium"
        path = "站可达但关键词命中少，可扩词或走地方分站"
    else:
        feasibility = "low"
        path = "需 WebBridge/人工辅助"

    return {
        "site": "中国政府采购网",
        "hosts": HOSTS,
        "reachable": http_ok and (home or {}).get("href", "").startswith("http"),
        "search_entry": search_entry,
        "list_fields": list_fields,
        "detail_fields": detail_fields,
        "amount_location": "list" if amount_in_list else ("detail" if amount_in_detail else "unknown"),
        "keyword_tests": keyword_tests,
        "detail_probe": detail_probe,
        "http_probe": http_results,
        "network_hits_sample": network_hits[:25],
        "blockers": blockers,
        "crawl_feasibility": feasibility,
        "government_site_openness": "较开放：公告列表与详情一般无需登录，政府站公开属性强",
        "http_list_sufficient": any_results and not any(
            b.get("type") in ("captcha_on_search",) and b.get("level") == "high" for b in blockers
        ),
        "recommended_path": path,
        "next_actions_for_user": [
            "用 search.ccgp.gov.cn/bxsearch?kw=关键词 做 HTTP 列表爬虫（分页 page_index）",
            "详情页解析标题/时间/采购人/预算金额；金额多在详情正文",
            "关键词可扩：花卉租摆、园林绿化、物业绿化",
            "若全国站结果少，叠加各省 ccgp 分站或地方政府采购网",
        ],
        "daemon": st,
    }


def main():
    st = ensure()
    if not st.get("extension_connected"):
        report = {"site": "中国政府采购网", "error": "extension not connected", "daemon": st}
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return

    try:
        call("network", {"cmd": "start"})
    except Exception:
        pass

    http_results = [http_get(u) for u in [
        "https://www.ccgp.gov.cn/",
        "https://search.ccgp.gov.cn/bxsearch?searchtype=1&page_index=1&bidSort=0&buyerName=&projectId=&pinMu=0&bidType=0&dbselect=bidx&kw=" + urllib.parse.quote("绿化养护"),
    ]]

    nav_home, home = probe_home()
    keyword_tests = [search_keyword(kw) for kw in KEYWORDS]

    sample_url = None
    for kt in keyword_tests:
        for it in (kt.get("page") or {}).get("items") or []:
            if it.get("href"):
                sample_url = it["href"]
                break
        if sample_url:
            break
    if not sample_url:
        # fallback from http probe links
        for h in http_results:
            for lnk in h.get("links") or []:
                if re.search(r"ccgp\\.gov\\.cn/.+/(\\d{4}|detail|info)", lnk.get("h", "")):
                    sample_url = lnk["h"]
                    break

    detail_probe = probe_detail(sample_url) if sample_url else {"skipped": "no_sample_url"}

    network_hits = collect_network()
    try:
        call("network", {"cmd": "stop"})
    except Exception:
        pass

    report = build_report(st, http_results, home, keyword_tests, detail_probe, network_hits)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", REPORT)
    print(json.dumps({
        "reachable": report["reachable"],
        "feasibility": report["crawl_feasibility"],
        "amount_location": report.get("amount_location"),
        "keywords_hit": [kt["keyword"] for kt in keyword_tests if (kt.get("page") or {}).get("result_count", 0) > 0],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
