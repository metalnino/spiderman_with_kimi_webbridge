"""WebBridge warm-session: open site, then HTTP can reuse jar if cookies injected."""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

from crawl.config_loader import ROOT, anti_bot_cfg
from crawl.http_session import HttpSession

WB = "http://127.0.0.1:10086/command"

WARM_URLS = {
    "ggzy": "https://www.ggzy.gov.cn/",
    "chinabidding": "https://www.chinabidding.com.cn/",
    "ccgp": "https://www.ccgp.gov.cn/",
    "cebpub": "https://bulletin.cebpubservice.com/",
}


def _wb_call(action: str, args: dict | None = None, session: str = "warm") -> dict:
    body = json.dumps({"action": action, "args": args or {}, "session": session}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(WB, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def should_warm(source_id: str) -> bool:
    if os.environ.get("SPIDER_FORCE_WARM") == "1":
        return True
    ab = anti_bot_cfg()
    per = (ab.get("per_source") or {}).get(source_id) or {}
    if per.get("primary") == "webbridge_or_warm_http":
        return True
    return per.get("warm") is True


def warm_source(source_id: str, http: HttpSession | None = None) -> dict:
    """Navigate via WebBridge when daemon available; never crash caller."""
    if not should_warm(source_id):
        return {"warmed": False, "reason": "not_required"}
    url = WARM_URLS.get(source_id)
    if not url:
        return {"warmed": False, "reason": "no_url"}
    try:
        nav = _wb_call("navigate", {"url": url, "newTab": True, "group_title": f"warm-{source_id}"})
        time.sleep(2)
        # Cookie export API may be unavailable; mark warm attempted
        out = {"warmed": bool(nav.get("ok")), "url": url, "nav_ok": nav.get("ok")}
        log = ROOT / "data" / "web" / "warm_log.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
        return out
    except Exception as e:  # noqa: BLE001
        return {"warmed": False, "reason": f"webbridge_unavailable:{e}"}
