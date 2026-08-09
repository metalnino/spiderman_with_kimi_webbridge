"""WebBridge warm-session hook (P0 stub + optional enable).

Principle: warm browser → cookies → reuse on HttpSession.
Full cookie export depends on WebBridge capability; P0 records intent.
"""
from __future__ import annotations

from crawl.config_loader import anti_bot_cfg


def should_warm(source_id: str) -> bool:
    ab = anti_bot_cfg()
    per = (ab.get("per_source") or {}).get(source_id) or {}
    warm = per.get("warm")
    if warm == "optional":
        return False  # P0 default off for speed; enable via config later
    return warm is True or per.get("primary") == "webbridge_or_warm_http"


def warm_source(source_id: str) -> dict:
    """Placeholder: returns skipped unless explicitly required."""
    if not should_warm(source_id):
        return {"warmed": False, "reason": "skipped_p0_default"}
    # Future: WebBridge navigate + export cookies into HttpSession
    return {"warmed": False, "reason": "hook_ready_not_wired"}
