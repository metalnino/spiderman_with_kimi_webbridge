"""WebBridge warm-session: open site, then HTTP can reuse jar if cookies injected."""
from __future__ import annotations

import json
import os
import time

from crawl import cookie_store, webbridge_client
from crawl.config_loader import ROOT, anti_bot_cfg

WARM_URLS = {
    "ggzy": "https://www.ggzy.gov.cn/",
    "chinabidding": "https://www.chinabidding.com.cn/",
    "ccgp": "https://www.ccgp.gov.cn/",
    "cebpub": "https://bulletin.cebpubservice.com/",
    "jsggzy": "http://jsggzy.jszwfw.gov.cn/",
    "jiangsu_zhaobiao": "https://jiangsu.zhaobiao.cn/",
}


def should_warm(source_id: str) -> bool:
    if os.environ.get("SPIDER_FORCE_WARM") == "1":
        return True
    ab = anti_bot_cfg()
    per = (ab.get("per_source") or {}).get(source_id) or {}
    if per.get("primary") == "webbridge_or_warm_http":
        return True
    return per.get("warm") is True


def warm_source(source_id: str, http=None) -> dict:
    """Navigate via WebBridge when daemon available; never crash caller."""
    if not should_warm(source_id):
        return {"warmed": False, "reason": "not_required"}
    url = WARM_URLS.get(source_id)
    if not url:
        return {"warmed": False, "reason": "no_url"}
    try:
        session = f"warm-{source_id}"
        nav = webbridge_client.navigate(url, session=session, group_title=f"warm-{source_id}")
        time.sleep(2)
        exported = webbridge_client.export_document_cookie(session)
        if exported.get("ok") and exported.get("cookie"):
            cookie_store.save_cookie_header(source_id, exported["cookie"], meta={"from": "warm"})
            if http is not None and hasattr(http, "load_stored_cookies"):
                http.load_stored_cookies(source_id)
        out = {
            "warmed": bool(nav.get("ok") or exported.get("cookie")),
            "url": url,
            "nav_ok": bool(nav.get("ok")),
            "cookie_saved": bool(exported.get("cookie")),
        }
        log = ROOT / "data" / "web" / "warm_log.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
        return out
    except Exception as e:  # noqa: BLE001
        return {"warmed": False, "reason": f"webbridge_unavailable:{e}"}
