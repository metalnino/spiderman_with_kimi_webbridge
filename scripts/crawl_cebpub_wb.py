"""cebpub 通过 WebBridge 浏览器爬取：渲染搜索页 → 填关键词 → 点搜索 → 抓列表 → 写 MySQL。

本机运行（需 Kimi 浏览器扩展已连接守护进程）。cebpub 搜索页已改 JS 渲染+加密，HTTP 不可用。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crawl.db_store import finish_run, start_run, upsert_notices  # noqa: E402
from crawl.keywords import enabled_keywords  # noqa: E402
from crawl.models import Notice  # noqa: E402

EXE = Path(os.environ["USERPROFILE"]) / ".kimi-webbridge" / "bin" / "kimi-webbridge.exe"
BASE = "http://127.0.0.1:10086/command"
SESSION = "cebpub-crawl"
SEARCH_URL = "https://www.cebpubservice.com/ctpsp_iiss/searchbusinesstypebeforedooraction/getSearch.do"
DETAIL_TPL = "https://ctbpsp.com/#/bulletinDetail?uuid={uuid}&inpvalue=&dataSource=0&tenderAgency="


def call(action: str, args: dict | None = None, timeout: int = 120) -> dict:
    body = json.dumps({"action": action, "args": args or {}, "session": SESSION}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def eval_js(code: str):
    r = call("evaluate", {"code": code})
    if not r.get("ok"):
        return None
    v = (r.get("data") or {}).get("value")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v


def match_city(title: str) -> str | None:
    from crawl.config_loader import cities as _cities

    hits = [c["name"] for c in _cities() if c["name"] in (title or "")]
    return hits[0] if hits else None


def do_search(kw: str) -> dict:
    code = (
        "(function(){var kw=" + json.dumps(kw) + ";"
        "var input=document.querySelector('#keySearchValue')||document.querySelector('input[name=keySearchValue]');"
        "if(!input)return JSON.stringify({ok:false,error:'no_input'});"
        "input.value=kw;"
        "input.dispatchEvent(new Event('input',{bubbles:true}));"
        "input.dispatchEvent(new Event('change',{bubbles:true}));"
        "var btn=[].slice.call(document.querySelectorAll('button,input[type=button],input[type=submit],a')).find(function(b){return /搜索|查询|检索/.test(b.textContent||b.value||'');});"
        "if(btn){btn.click();return JSON.stringify({ok:true,method:'click'});}"
        "if(typeof query==='function'){query();return JSON.stringify({ok:true,method:'query_fn'});}"
        "return JSON.stringify({ok:false,error:'no_trigger'});"
        "})()"
    )
    return eval_js(code) or {}


def extract_results() -> list[dict]:
    code = (
        "(function(){var out=[];var as=document.querySelectorAll('a');"
        "for(var i=0;i<as.length;i++){var href=as[i].getAttribute('href')||'';"
        "if(href.indexOf('urlOpen')>=0){out.push({href:href,title:(as[i].textContent||'').replace(/\s+/g,' ').trim()});}}"
        "return JSON.stringify(out);})()"
    )
    raw = eval_js(code) or []
    items = []
    for it in raw:
        m = re.search(r"urlOpen\('([0-9a-fA-F]{16,})'\)", it.get("href") or "")
        if m and len(it.get("title") or "") >= 4:
            items.append({"uuid": m.group(1), "title": it["title"]})
    return items


def ensure_daemon() -> dict:
    subprocess.run([str(EXE), "start"], check=False)
    time.sleep(2)
    st = json.loads(subprocess.check_output([str(EXE), "status"], text=True))
    return st


def main(keywords: list[str] | None = None) -> None:
    st = ensure_daemon()
    if not st.get("extension_connected"):
        print(json.dumps({"ok": False, "error": "webbridge_extension_not_connected", "hint": "请打开 Kimi 浏览器扩展"}, ensure_ascii=False))
        return

    kws = keywords or enabled_keywords()
    run_id = start_run("cebpub")
    notices: list[Notice] = []
    try:
        for i, kw in enumerate(kws):
            call("navigate", {"url": SEARCH_URL, "newTab": i == 0, "group_title": "cebpub-crawl"})
            time.sleep(5)
            trig = do_search(kw)
            time.sleep(6)
            items = extract_results()
            print(f"[cebpub-wb] {kw} trig={trig.get('method') or trig.get('error')} items={len(items)}", flush=True)
            for it in items:
                notices.append(
                    Notice(
                        source_id="cebpub",
                        source_name="中国招标投标公共服务平台",
                        external_id=it["uuid"],
                        title=it["title"],
                        city=match_city(it["title"]),
                        keyword=kw,
                        detail_url=DETAIL_TPL.format(uuid=it["uuid"]),
                        official_url=DETAIL_TPL.format(uuid=it["uuid"]),
                        bid_status="未知",
                    )
                )
            time.sleep(3)
        stats = upsert_notices(notices)
        finish_run(run_id, status="success", item_count=stats["attempted"], note=f"cebpub-wb items={len(notices)}")
        print(json.dumps({"items": len(notices), **stats}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        finish_run(run_id, status="failed", item_count=0, note=str(e)[:500])
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", default="", help="comma keywords; empty=all enabled")
    args = ap.parse_args()
    kws = [k.strip() for k in args.keywords.split(",") if k.strip()] or None
    main(kws)
