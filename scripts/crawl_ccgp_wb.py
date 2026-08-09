"""CCGP trial via WebBridge (HTTP 易触发频繁访问)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.parse
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "trial_multi"
EXE = Path(os.environ["USERPROFILE"]) / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe"
BASE = "http://127.0.0.1:10086/command"
SESSION = "ccgp-crawl"
SOURCES = json.loads((ROOT / "config" / "sources.json").read_text(encoding="utf-8"))
CRAWL = json.loads((ROOT / "config" / "crawl_config.json").read_text(encoding="utf-8"))


def call(action, args=None, timeout=180):
    body = {"action": action, "args": args or {}, "session": SESSION}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    import urllib.request

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
            return {"raw": v[:2000]}
    return v


def parse_list_from_dom():
    return eval_js(
        """(() => {
      const text = (document.body.innerText||'').replace(/\\s+/g,' ');
      if (/访问过于频繁|频繁访问/.test(text+document.title)) {
        return JSON.stringify({rate_limited:true, title:document.title, textHead:text.slice(0,200)});
      }
      const totalM = text.match(/共找到\\s*([\\d,]+)\\s*条/);
      const total = totalM ? parseInt(totalM[1].replace(/,/g,''),10) : null;
      const links = [...document.querySelectorAll('a')].filter(a => /ccgp\\.gov\\.cn\\/cggg\\//.test(a.href));
      const items = [];
      const seen = new Set();
      for (const a of links) {
        if (seen.has(a.href)) continue;
        seen.add(a.href);
        const title = (a.textContent||'').replace(/\\s+/g,' ').trim();
        if (title.length < 4) continue;
        const row = (a.closest('li,tr,div')||a.parentElement);
        const rowText = (row && row.innerText || '').replace(/\\s+/g,' ').trim();
        const buyerM = rowText.match(/采购人[：:]\\s*([^|]+)/);
        const agencyM = rowText.match(/代理机构[：:]\\s*([^|]+)/);
        const timeM = rowText.match(/(20\\d{2}[\\.\\-]\\d{2}[\\.\\-]\\d{2}\\s+\\d{2}:\\d{2}:\\d{2})/);
        items.push({
          title,
          detail_url: a.href.replace('http://','https://'),
          buyer: buyerM ? buyerM[1].trim().slice(0,80) : null,
          agency: agencyM ? agencyM[1].trim().slice(0,80) : null,
          publish_date: timeM ? timeM[1].replace(/\\./g,'-') : null,
          row_head: rowText.slice(0,220)
        });
      }
      return JSON.stringify({rate_limited:false, total, count:items.length, items:items.slice(0,40), href:location.href, title:document.title});
    })()"""
    )


def match_cities(title: str, cities: list) -> list:
    hits = [c["name"] for c in cities if c["name"] in title]
    return hits


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(EXE), "start"], check=False)
    time.sleep(1)
    st = json.loads(subprocess.check_output([str(EXE), "status"], text=True))
    if not st.get("extension_connected"):
        raise SystemExit("webbridge extension not connected")

    keywords = list((SOURCES.get("defaults") or {}).get("trial_keywords") or ["绿植租摆", "绿化养护"])
    # 频控下先少抓：每词 1 页
    max_pages = 1
    time_type = str((SOURCES.get("ccgp") or {}).get("time_type") or "5")
    cities = CRAWL.get("cities") or []

    rows = []
    stats = []
    for kw in keywords:
        for page in range(1, max_pages + 1):
            q = urllib.parse.urlencode(
                {
                    "searchtype": "1",
                    "page_index": str(page),
                    "bidSort": "0",
                    "buyerName": "",
                    "projectId": "",
                    "pinMu": "0",
                    "bidType": "0",
                    "dbselect": "bidx",
                    "kw": kw,
                    "timeType": time_type,
                }
            )
            url = "https://search.ccgp.gov.cn/bxsearch?" + q
            nav = call("navigate", {"url": url, "newTab": page == 1 and kw == keywords[0], "group_title": "ccgp-crawl"})
            time.sleep(8)
            data = parse_list_from_dom()
            err = None
            if data.get("rate_limited"):
                err = "rate_limited"
                print(f"[ccgp-wb] {kw} rate-limited, sleep 60s", flush=True)
                time.sleep(60)
                call("navigate", {"url": url, "newTab": False})
                time.sleep(8)
                data = parse_list_from_dom()
                if data.get("rate_limited"):
                    err = "rate_limited"
            items = data.get("items") or []
            stats.append(
                {
                    "keyword": kw,
                    "page": page,
                    "url": url,
                    "nav_ok": nav.get("ok"),
                    "count": len(items),
                    "total": data.get("total"),
                    "error": err if data.get("rate_limited") else None,
                }
            )
            print(
                f"[ccgp-wb] {kw} p{page} -> {len(items)} total={data.get('total')} err={stats[-1]['error']}",
                flush=True,
            )
            for it in items:
                rows.append(
                    {
                        **it,
                        "keyword": kw,
                        "cities": match_cities(it.get("title") or "", cities),
                        "source": "中国政府采购网",
                        "source_id": "ccgp",
                        "via": "webbridge",
                    }
                )
            time.sleep(10)
            if data.get("rate_limited"):
                break

    # sample 2 details via browser
    detail_samples = 0
    for r in rows:
        if detail_samples >= 3:
            break
        if not r.get("detail_url"):
            continue
        call("navigate", {"url": r["detail_url"], "newTab": False})
        time.sleep(6)
        det = eval_js(
            """(() => {
          const text=(document.body.innerText||'').replace(/\\s+/g,' ');
          if (/访问过于频繁/.test(text)) return JSON.stringify({rate_limited:true});
          const out={};
          const m1=text.match(/采购项目编号[：:]\\s*([A-Za-z0-9\\-_/]+)/) || text.match(/项目编号[：:]\\s*([A-Za-z0-9\\-_/]+)/);
          if (m1) out.project_code=m1[1];
          const m2=text.match(/预算金额[：:]\\s*([^。；;]{1,40})/) || text.match(/预算[：:]\\s*([0-9,.]+)\\s*元/);
          if (m2) out.amount_text=m2[1].trim();
          const m3=text.match(/采购人[：:]\\s*([^。；;]{2,60})/);
          if (m3) out.buyer=m3[1].trim();
          const num=(out.amount_text||'').match(/([\\d,.]+)/);
          if (num) out.amount=parseFloat(num[1].replace(/,/g,''));
          return JSON.stringify(out);
        })()"""
        )
        if det.get("rate_limited"):
            r["detail_error"] = "rate_limited"
            break
        r["detail"] = det
        if det.get("amount_text"):
            r["amount_text"] = det["amount_text"]
        if det.get("amount") is not None:
            r["amount"] = det["amount"]
        if det.get("buyer") and not r.get("buyer"):
            r["buyer"] = det["buyer"]
        if det.get("project_code"):
            r["project_code"] = det["project_code"]
        detail_samples += 1
        print(f"[ccgp-wb-detail] {r['title'][:36]} amount={r.get('amount_text')}", flush=True)
        time.sleep(8)

    seen = set()
    deduped = []
    for r in rows:
        u = r.get("detail_url")
        if u in seen:
            continue
        seen.add(u)
        deduped.append(r)

    summary = {
        "source": "ccgp",
        "via": "webbridge",
        "keywords": keywords,
        "list_items": len(deduped),
        "with_amount": sum(1 for r in deduped if r.get("amount") or r.get("amount_text")),
        "city_tagged": sum(1 for r in deduped if r.get("cities")),
        "stats": stats,
        "sample_titles": [r["title"] for r in deduped[:10]],
        "daemon": st,
    }
    (OUT / "ccgp_items.json").write_text(json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "ccgp_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    # refresh multi summary lightly
    multi_path = OUT / "multi_summary.json"
    multi = json.loads(multi_path.read_text(encoding="utf-8")) if multi_path.exists() else {"sources": {}, "totals": {}}
    multi.setdefault("sources", {})["ccgp"] = summary
    multi.setdefault("totals", {})["by_source"] = multi.get("totals", {}).get("by_source") or {}
    multi["totals"]["by_source"]["ccgp"] = len(deduped)
    multi["totals"]["items"] = sum(multi["totals"]["by_source"].get(k, 0) for k in ("ccgp", "ggzy", "chinabidding"))
    multi_path.write_text(json.dumps(multi, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"list_items": len(deduped), "with_amount": summary["with_amount"]}, ensure_ascii=False))
    print("WROTE", OUT / "ccgp_items.json")


if __name__ == "__main__":
    main()
