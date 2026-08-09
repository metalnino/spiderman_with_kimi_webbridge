"""WebBridge probe: 全国公共资源交易平台 ggzy.gov.cn"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "multi_site"
OUT.mkdir(parents=True, exist_ok=True)
EXE = Path(os.environ["USERPROFILE"]) / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe"
BASE = "http://127.0.0.1:10086/command"
SESSION = "ggzy-probe"
KEYWORDS = ["绿植租摆", "绿化养护"]
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def call(action, args=None, timeout=120):
    body = {"action": action, "args": args or {}, "session": SESSION}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_probe(url: str) -> dict:
    r = {"url": url, "ok": False}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            raw = resp.read()
            r["status"] = resp.status
            r["final"] = resp.geturl()
            r["ok"] = True
            r["len"] = len(raw)
            for enc in ("utf-8", "gbk", "gb2312"):
                try:
                    html = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    html = None
            if not html:
                html = raw.decode("utf-8", "ignore")
            m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            r["title"] = re.sub(r"\s+", " ", unescape(m.group(1))).strip() if m else ""
            links = []
            for t, h in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, re.I | re.S)[:200]:
                text = re.sub(r"<[^>]+>", "", t)
                text = re.sub(r"\s+", " ", unescape(text)).strip()
                if len(text) < 2:
                    continue
                links.append({"t": text[:80], "h": h[:300]})
            r["links_sample"] = links[:30]
    except Exception as e:  # noqa: BLE001
        r["error"] = str(e)
    return r


def ensure_daemon():
    subprocess.run([str(EXE), "start"], check=False)
    time.sleep(2)
    return json.loads(subprocess.check_output([str(EXE), "status"], text=True))


def extract_links_from_eval(value: dict) -> list:
    rows = value.get("rows") or value.get("links") or []
    if isinstance(rows, list):
        return rows
    return []


def network_hits(nets: dict) -> list:
    hits = []
    data = nets.get("data") if nets.get("ok") else None
    entries = []
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = data.get("requests") or data.get("items") or []
        if not entries:
            entries = [v for v in data.values() if isinstance(v, dict) and ("url" in v or "request" in v)]
    for e in entries[:500]:
        if not isinstance(e, dict):
            continue
        u = e.get("url") or (e.get("request") or {}).get("url") or ""
        if any(k in u.lower() for k in ["search", "api", "list", "query", "deal", "trade", "ajax", "page", "notice", "bulletin"]):
            hits.append({
                "method": e.get("method") or (e.get("request") or {}).get("method"),
                "status": e.get("status") or (e.get("response") or {}).get("status"),
                "url": u[:600],
            })
    return hits


def main():
    daemon = ensure_daemon()
    report = {
        "site": "全国公共资源交易平台",
        "hosts": ["www.ggzy.gov.cn", "deal.ggzy.gov.cn"],
        "reachable": {},
        "search_entry": {},
        "list_fields": [],
        "detail_fields": [],
        "keyword_tests": [],
        "blockers": [],
        "crawl_feasibility": "",
        "recommended_path": "",
        "next_actions_for_user": [],
        "notes_vs_cebpub": "",
        "probe_meta": {"daemon": daemon, "session": SESSION},
    }

    # HTTP reachability
    for u in [
        "https://www.ggzy.gov.cn/",
        "https://deal.ggzy.gov.cn/",
        "http://deal.ggzy.gov.cn/",
    ]:
        report["reachable"][u] = http_probe(u)

    if not daemon.get("extension_connected"):
        report["blockers"].append("WebBridge 扩展未连接，仅完成 HTTP 探针")
        report["crawl_feasibility"] = "低：需先连接浏览器扩展"
        out_path = OUT / "ggzy_report.json"
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("WROTE", out_path)
        return

    try:
        call("network", {"cmd": "start"})
    except Exception as e:  # noqa: BLE001
        report["probe_meta"]["network_start_error"] = str(e)

    # Navigate homepage
    nav = call("navigate", {"url": "https://www.ggzy.gov.cn/", "newTab": True, "group_title": "ggzy探针"})
    report["probe_meta"]["nav_home"] = {"ok": nav.get("ok"), "url": (nav.get("data") or {}).get("url")}
    time.sleep(6)

    home_eval = call(
        "evaluate",
        {
            "code": """(() => {
      const links=[...document.querySelectorAll('a')].map(a=>({
        t:(a.textContent||'').trim().slice(0,60),
        h:a.href,
        host: (()=>{try{return new URL(a.href).hostname}catch(e){return ''}})()
      })).filter(x=>x.t && x.h && !x.h.startsWith('javascript'));
      const searchInput = document.querySelector('input[type=search], input[placeholder*=搜索], input[placeholder*=检索], input[name*=keyword], input#keyword, .search input');
      const searchBtn = [...document.querySelectorAll('button,a,span')].find(el=>/搜索|查询|检索/.test((el.textContent||'').trim()));
      const tradeLinks = links.filter(x=>/交易|公告|采购|招标|信息|deal|search/i.test(x.t+x.h)).slice(0,40);
      const hosts = [...new Set(links.map(x=>x.host).filter(Boolean))].slice(0,30);
      return JSON.stringify({
        href: location.href,
        title: document.title,
        hasSearchInput: !!searchInput,
        searchPlaceholder: searchInput ? (searchInput.placeholder||searchInput.name||'') : '',
        hasSearchBtn: !!searchBtn,
        tradeLinks,
        hosts,
        textHead: (document.body.innerText||'').replace(/\\s+/g,' ').slice(0,1200)
      });
    })()"""
        },
    )
    home_data = {}
    if home_eval.get("ok"):
        home_data = json.loads(home_eval["data"]["value"])
    report["search_entry"]["homepage"] = home_data
    report["probe_meta"]["home_hosts"] = home_data.get("hosts", [])

    # Try deal.ggzy.gov.cn
    nav2 = call("navigate", {"url": "https://deal.ggzy.gov.cn/", "newTab": False})
    time.sleep(6)
    deal_eval = call(
        "evaluate",
        {
            "code": """(() => {
      const links=[...document.querySelectorAll('a')].map(a=>({t:(a.textContent||'').trim().slice(0,80),h:a.href}))
        .filter(x=>x.t.length>1);
      const inputs=[...document.querySelectorAll('input')].map(i=>({type:i.type,ph:i.placeholder,name:i.name,id:i.id}));
      const rows=[...document.querySelectorAll('tr, li, .list-item, .el-table__row, .notice-item')].slice(0,30)
        .map(el=>(el.innerText||'').replace(/\\s+/g,' ').trim().slice(0,150)).filter(t=>t.length>15);
      return JSON.stringify({href:location.href,title:document.title,inputs,tradeLinks:links.filter(x=>/交易|公告|采购|招标|搜索|查询/.test(x.t+x.h)).slice(0,25),rows,textHead:(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,1500)});
    })()"""
        },
    )
    deal_data = json.loads(deal_eval["data"]["value"]) if deal_eval.get("ok") else {}
    report["search_entry"]["deal_portal"] = deal_data

    # Find search URL from links
    search_urls = []
    for src in [home_data, deal_data]:
        for lk in (src.get("tradeLinks") or []):
            h = lk.get("h", "")
            if re.search(r"search|query|list|deal|jyxx|notice", h, re.I):
                search_urls.append(h)
    # common ggzy search patterns
    search_urls.extend([
        "https://deal.ggzy.gov.cn/ds/deal/dealList.jsp",
        "https://deal.ggzy.gov.cn/ds/deal/dealList_find.jsp",
    ])
    search_urls = list(dict.fromkeys(search_urls))[:5]
    report["search_entry"]["candidate_urls"] = search_urls

    # Keyword tests
    for kw in KEYWORDS:
        kt = {"keyword": kw, "ok": False, "result_count_visible": 0, "sample_titles": [], "list_url": "", "detail_probe": {}}
        # navigate to deal list if possible
        list_url = search_urls[0] if search_urls else "https://deal.ggzy.gov.cn/"
        call("navigate", {"url": list_url, "newTab": False})
        time.sleep(4)

        search_act = call(
            "evaluate",
            {
                "code": f"""(() => {{
      const kw = {json.dumps(kw)};
      let input = document.querySelector('input[type=search], input[placeholder*=关键词], input[placeholder*=搜索], input[name*=keyword], input#keyword, input[type=text]');
      const allInputs = [...document.querySelectorAll('input')];
      if (!input) input = allInputs.find(i => i.type==='text' || i.type==='search');
      if (input) {{
        input.focus();
        input.value = kw;
        input.dispatchEvent(new Event('input', {{bubbles:true}}));
        input.dispatchEvent(new Event('change', {{bubbles:true}}));
      }}
      let clicked=false;
      for (const b of document.querySelectorAll('button,a,span,input[type=button],input[type=submit]')) {{
        const t=((b.textContent||'')+(b.value||'')+(b.getAttribute('aria-label')||'')).trim();
        if (/搜索|查询|检索|搜一下/.test(t)) {{ b.click(); clicked=true; break; }}
      }}
      if (!clicked && input) {{
        input.dispatchEvent(new KeyboardEvent('keydown', {{key:'Enter',bubbles:true}}));
        input.dispatchEvent(new KeyboardEvent('keyup', {{key:'Enter',bubbles:true}}));
      }}
      const links=[...document.querySelectorAll('a')].map(a=>({{t:(a.textContent||'').trim(),h:a.href}}))
        .filter(x=>x.t.length>6);
      const matched = links.filter(x=>x.t.includes(kw) || /绿化|绿植|租摆|养护|园林|花卉/.test(x.t));
      const rows=[...document.querySelectorAll('tr, li, .list-item, .el-table__row, .notice-item, .news-item')].slice(0,50)
        .map(el=>(el.innerText||'').replace(/\\s+/g,' ').trim()).filter(t=>t.length>10);
      const matchedRows = rows.filter(t=>t.includes(kw) || /绿化|绿植|租摆|养护/.test(t));
      const text=(document.body.innerText||'').replace(/\\s+/g,' ');
      const countMatch = text.match(/共\\s*(\\d+)\\s*条|找到\\s*(\\d+)\\s*条|总计\\s*(\\d+)/);
      return JSON.stringify({{
        href:location.href, title:document.title,
        hasInput:!!input, clicked,
        matchedCount: matched.length,
        matchedRowsCount: matchedRows.length,
        countHint: countMatch ? countMatch[0] : '',
        matched: matched.slice(0,15),
        matchedRows: matchedRows.slice(0,10),
        allLinksSample: links.slice(0,20),
        loginHint: /登录|验证码|会员|注册/.test(text),
        textHead: text.slice(0,1000)
      }});
    }})()"""
            },
        )
        time.sleep(5)
        after = call(
            "evaluate",
            {
                "code": f"""(() => {{
      const kw = {json.dumps(kw)};
      const links=[...document.querySelectorAll('a')].map(a=>({{t:(a.textContent||'').trim(),h:a.href}}))
        .filter(x=>x.t.length>6);
      const matched = links.filter(x=>x.t.includes(kw) || /绿化|绿植|租摆|养护|园林|花卉/.test(x.t));
      const rows=[...document.querySelectorAll('tr, li, .list-item, .el-table__row')].slice(0,60)
        .map(el=>(el.innerText||'').replace(/\\s+/g,' ').trim()).filter(t=>t.length>10);
      const matchedRows = rows.filter(t=>t.includes(kw) || /绿化|绿植|租摆|养护/.test(t));
      return JSON.stringify({{href:location.href, matched:matched.slice(0,20), matchedRows:matchedRows.slice(0,15), rowCount:rows.length}});
    }})()"""
            },
        )
        act_data = json.loads(search_act["data"]["value"]) if search_act.get("ok") else {}
        after_data = json.loads(after["data"]["value"]) if after.get("ok") else {}
        merged = {**act_data, **after_data}
        kt["list_url"] = merged.get("href", list_url)
        kt["has_search_input"] = merged.get("hasInput")
        kt["search_clicked"] = merged.get("clicked")
        kt["login_hint"] = merged.get("loginHint")
        kt["count_hint"] = merged.get("countHint", "")
        samples = merged.get("matched") or []
        if not samples:
            samples = [{"t": r, "h": ""} for r in (merged.get("matchedRows") or [])[:10]]
        kt["sample_titles"] = [s.get("t", s) if isinstance(s, dict) else s for s in samples[:10]]
        kt["result_count_visible"] = max(
            merged.get("matchedCount", 0),
            merged.get("matchedRowsCount", 0),
            len(merged.get("matched") or []),
            len(merged.get("matchedRows") or []),
        )
        kt["ok"] = kt["result_count_visible"] > 0
        kt["page_text_head"] = merged.get("textHead", "")[:500]

        # Try open first detail
        detail_href = None
        for s in (merged.get("matched") or []):
            if isinstance(s, dict) and s.get("h") and s["h"].startswith("http"):
                detail_href = s["h"]
                break
        if detail_href:
            call("navigate", {"url": detail_href, "newTab": False})
            time.sleep(4)
            det = call(
                "evaluate",
                {
                    "code": """(() => {
          const text=(document.body.innerText||'').replace(/\\s+/g,' ');
          const fields={};
          for (const label of ['项目名称','公告标题','采购人','招标人','中标金额','预算金额','成交金额','发布时间','公告时间','所在地区','行政区域']) {
            const re=new RegExp(label+'[：:\\s]*([^\\n]{2,80})');
            const m=text.match(re);
            if (m) fields[label]=m[1].trim();
          }
          return JSON.stringify({
            href:location.href, title:document.title,
            loginRequired:/请登录|登录后|会员|验证码/.test(text),
            captcha:/验证码|captcha|滑动验证/.test(text.toLowerCase()+text),
            amountVisible:/金额|万元|元/.test(text),
            fields,
            textHead:text.slice(0,1200)
          });
        })()"""
                },
            )
            if det.get("ok"):
                kt["detail_probe"] = json.loads(det["data"]["value"])
        report["keyword_tests"].append(kt)

    # Network capture
    nets = call("network", {"cmd": "list"})
    try:
        call("network", {"cmd": "stop"})
    except Exception:
        pass
    hits = network_hits(nets)
    report["probe_meta"]["network_hits"] = hits[:80]

    # Infer list/detail fields from keyword tests
    all_rows_text = []
    for kt in report["keyword_tests"]:
        all_rows_text.extend(kt.get("sample_titles") or [])
    list_guess = set()
    for t in all_rows_text:
        ts = str(t)
        if re.search(r"\d{4}[-/年]\d{1,2}", ts):
            list_guess.add("发布时间")
        if re.search(r"(北京|上海|广东|省|市|区|县)", ts):
            list_guess.add("地区")
        if re.search(r"(万元|元|预算|金额)", ts):
            list_guess.add("金额")
    list_guess.add("标题")
    report["list_fields"] = sorted(list_guess)

    detail_fields = set()
    for kt in report["keyword_tests"]:
        for k in (kt.get("detail_probe") or {}).get("fields", {}):
            detail_fields.add(k)
    if not detail_fields:
        detail_fields = {"公告标题", "发布时间", "采购人/招标人", "金额(可能需登录)"}
    report["detail_fields"] = sorted(detail_fields)

    # Blockers
    if any(kt.get("login_hint") for kt in report["keyword_tests"]):
        report["blockers"].append("列表或详情页出现登录/会员提示")
    for kt in report["keyword_tests"]:
        dp = kt.get("detail_probe") or {}
        if dp.get("captcha"):
            report["blockers"].append("详情页可能存在验证码")
        if dp.get("loginRequired"):
            report["blockers"].append("详情页可能需要登录")
    if not any(kt.get("ok") for kt in report["keyword_tests"]):
        report["blockers"].append("关键词搜索未获得可见匹配结果（可能入口不对或需跳转地方站）")

    # Redirect / portal analysis
    home_hosts = set(home_data.get("hosts") or [])
    deal_href = deal_data.get("href", "")
    redirect_notes = []
    if deal_href and "ggzy" in deal_href:
        redirect_notes.append(f"deal 子域可达: {deal_href}")
    ext_hosts = [h for h in home_hosts if h and "ggzy.gov.cn" not in h]
    if ext_hosts:
        redirect_notes.append(f"首页外链地方平台样例: {ext_hosts[:8]}")
    report["search_entry"]["redirect_notes"] = redirect_notes

    # Feasibility & recommendations
    has_results = any(kt.get("ok") for kt in report["keyword_tests"])
    has_api = len(hits) > 0
    if has_results and not report["blockers"]:
        report["crawl_feasibility"] = "中高：可抓列表+详情，建议先固化 deal 列表 API"
    elif has_results:
        report["crawl_feasibility"] = "中：列表可搜到结果，但详情可能有登录/验证码"
    elif has_api:
        report["crawl_feasibility"] = "中低：有接口痕迹但关键词无结果，需找对搜索 API 或地方站"
    else:
        report["crawl_feasibility"] = "低：门户跳转为主，全国统一检索弱，宜抓地方子站"

    if has_api:
        api_urls = [h["url"] for h in hits[:5]]
        report["recommended_path"] = (
            "优先 deal.ggzy.gov.cn 交易列表/搜索接口 HTTP 抓取；"
            f"样例 API: {'; '.join(api_urls[:3])}"
        )
    else:
        report["recommended_path"] = (
            "www.ggzy.gov.cn 为聚合门户，实际公告在 deal.ggzy.gov.cn 或各省子域；"
            "建议按省平台分别配置爬虫，全国站只做入口发现"
        )

    report["next_actions_for_user"] = [
        "确认 deal.ggzy.gov.cn 列表/搜索的正确 URL 与 POST 参数（network 已采样）",
        "对命中详情页人工打开一次，确认金额字段是否公开",
        "若全国检索无结果，改为配置重点省份 ggzy 子站（首页 hosts 列表）",
        "与 cebpub 去重：同一公告可能同时在 cebpub 与地方 ggzy 发布",
    ]

    report["notes_vs_cebpub"] = (
        "ggzy 是全国公共资源交易「门户+跳转」体系：www.ggzy.gov.cn 聚合各地交易中心链接，"
        "deal.ggzy.gov.cn 提供部分全国交易公告检索；cebpub（bulletin.cebpubservice.com）是"
        "招标投标公告公示标准发布平台，数据源有重叠但不等同——ggzy 更偏公共资源交易全品类+地方落地，"
        "cebpub 更偏依法必须招标的公告；同一项目可能两处都有，宜以 cebpub UUID 为主键做去重，"
        "ggzy 作地区交易补充。"
    )

    out_path = OUT / "ggzy_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", out_path)
    print(json.dumps({
        "reachable": {k: v.get("ok") for k, v in report["reachable"].items()},
        "keyword_ok": [kt["keyword"] + ":" + str(kt["ok"]) for kt in report["keyword_tests"]],
        "blockers": report["blockers"],
        "network": len(hits),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
