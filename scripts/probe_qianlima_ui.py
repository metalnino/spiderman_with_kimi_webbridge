"""千里马 UI 真人流探针（只读，单词单遍，谨慎模式）。

思路：不再直连搜索 API（CloudWAF 418），而是像真人一样——
首页落地 → 搜索页渲染（SPA 自身发请求，带齐 WAF cookie/token）→ 读 DOM + 抓网络响应。
纪律：单关键词、单遍、随机停顿、遇拦截立即停手不轰炸；证据落 data/qianlima_ui_probe.json。
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys  # noqa: E402

sys.path.insert(0, str(ROOT))
from crawl import webbridge_client as wb  # noqa: E402

OUT = ROOT / "data" / "qianlima_ui_probe.json"
KW = "绿植租摆"
SESSION = "qlm-probe"


def jitter(lo: float, hi: float) -> None:
    time.sleep(random.uniform(lo, hi))


def call2(action: str, args: dict) -> dict:
    r = wb.call(action, args, session=SESSION, timeout=60)
    return r


def main() -> None:
    report: dict = {"kw": KW, "steps": []}
    st = wb.ensure_bridge(wait_sec=60)
    report["bridge"] = {"up": st.get("bridge"), "extensions": st.get("extensions")}
    if not st.get("extensions"):
        report["error"] = "extension_not_connected"
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return

    # 1) 真人入口：先落官网首页，给 WAF 挑战/cookie 时间
    nav1 = call2("navigate", {"url": "https://www.qianlima.com/", "newTab": True, "group_title": "qianlima-probe"})
    report["steps"].append({"step": "home_nav", "ok": nav1.get("ok"), "err": nav1.get("error")})
    jitter(6, 9)

    ck = wb.export_cookies("https://www.qianlima.com/", session=SESSION)
    report["home_cookies"] = {
        "ok": ck.get("ok"),
        "names": [c.get("name") for c in (ck.get("cookies") or [])][:20],
    }

    # 2) 开网络抓包
    net_start = call2("network", {"cmd": "start"})
    report["steps"].append({"step": "network_start", "ok": net_start.get("ok"), "err": net_start.get("error")})

    # 3) 真人搜索流：带关键词的搜索页 URL（等于站内搜索跳转）
    search_url = f"https://search.qianlima.com/?q={KW}"
    nav2 = call2("navigate", {"url": search_url, "newTab": False})
    report["steps"].append({"step": "search_nav", "ok": nav2.get("ok"), "err": nav2.get("error")})
    jitter(10, 14)  # 给 SPA + 结果渲染留足时间

    # 4) 页面状态
    snap = call2("snapshot", {})
    if snap.get("ok"):
        d = snap.get("data") or {}
        report["page"] = {"title": d.get("title"), "url": d.get("url")}
        tree = json.dumps(d.get("tree"), ensure_ascii=False)
        report["page"]["tree_head"] = tree[:2500]
    else:
        report["page"] = {"snapshot_error": snap.get("error")}

    def read_page() -> dict:
        r = call2("evaluate", {
            "code": """(() => {
              const rows=[...document.querySelectorAll('a')].map(a=>({t:(a.textContent||'').trim().slice(0,100),h:a.href}))
                .filter(x=>x.t.length>8 && /绿化|租摆|养护|植物|花卉|采购|招标|公告|成交/.test(x.t)).slice(0,30);
              const text=(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,1500);
              return JSON.stringify({href:location.href,title:document.title,rows,textHead:text,cookie:(document.cookie||'').slice(0,300)});
            })()"""
        })
        if r.get("ok") and isinstance(r.get("data"), dict):
            v = r["data"].get("value")
            try:
                return json.loads(v) if isinstance(v, str) else v
            except Exception:
                return {"raw": str(v)[:1500]}
        return {"error": r.get("error")}

    page1 = read_page()
    report["page1"] = page1

    # 5) 若没有结果，做一次真实输入+点按钮（模拟真人搜索动作）
    if not (page1 or {}).get("rows"):
        act = call2("evaluate", {
            "code": f"""(() => {{
              const kw = {json.dumps(KW)};
              const input = document.querySelector('input[type=text], input[type=search], input[placeholder*="搜索"], input[placeholder*="关键词"], input.el-input__inner');
              if (input) {{
                input.focus();
                input.value = kw;
                input.dispatchEvent(new Event('input', {{bubbles:true}}));
                input.dispatchEvent(new Event('change', {{bubbles:true}}));
              }}
              let clicked=false;
              const btns=[...document.querySelectorAll('button,a,span,i,div')];
              for (const b of btns.slice(0,400)) {{
                const t=((b.textContent||'')+(b.getAttribute('aria-label')||'')).trim();
                if (t==='搜索' || t==='查询' || t==='搜 索') {{ b.click(); clicked=true; break; }}
              }}
              return JSON.stringify({{hasInput:!!input, clicked}});
            }})()"""
        })
        report["steps"].append({"step": "ui_search_act", "ok": act.get("ok"), "data": act.get("data")})
        jitter(9, 13)
        page2 = read_page()
        report["page2"] = page2

    # 6) 网络：找 SPA 发出的搜索 API 请求与响应
    nets = call2("network", {"cmd": "list"})
    try:
        call2("network", {"cmd": "stop"})
    except Exception:
        pass
    api_hits = []
    data = nets.get("data") if nets.get("ok") else None
    entries = data if isinstance(data, list) else ((data or {}).get("requests") or (data or {}).get("items") or [])
    for e in entries[:400]:
        if not isinstance(e, dict):
            continue
        u = e.get("url") or (e.get("request") or {}).get("url") or ""
        if "website/search" not in str(u) and "search.qianlima.com" not in str(u):
            continue
        resp = e.get("response") or {}
        body = resp.get("body")
        hit = {
            "method": e.get("method") or (e.get("request") or {}).get("method"),
            "status": e.get("status") or resp.get("status"),
            "url": str(u)[:400],
        }
        if isinstance(body, str):
            hit["body_head"] = body[:1500]
        elif isinstance(body, dict):
            hit["body"] = body
        api_hits.append(hit)
    report["api_requests"] = api_hits

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({
        "bridge_ext": st.get("extensions"),
        "page_rows": len((page1 or {}).get("rows") or []) + len((report.get("page2") or {}).get("rows") or []),
        "api_requests": len(api_hits),
        "api_statuses": [h.get("status") for h in api_hits],
        "waf_hint": "疑似恶意攻击" in (report.get("page1") or {}).get("textHead", ""),
        "out": str(OUT),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
