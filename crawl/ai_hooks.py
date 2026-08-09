from __future__ import annotations

import json
from pathlib import Path

from crawl.config_loader import ROOT
from crawl.pipeline.clean import CleanResult, clean_title

CFG_PATH = ROOT / "config" / "ai_hooks.json"


def load_ai_cfg() -> dict:
    if not CFG_PATH.exists():
        return {"enabled": False, "endpoint": "", "timeout_sec": 8}
    return json.loads(CFG_PATH.read_text(encoding="utf-8"))


def classify_relevance(title: str) -> CleanResult:
    """AI hook; default off → rule. If enabled and fails → degrade to rule."""
    cfg = load_ai_cfg()
    if not cfg.get("enabled"):
        return clean_title(title)
    try:
        # Placeholder HTTP call site — no real key required when disabled
        endpoint = cfg.get("endpoint") or ""
        if not endpoint:
            raise RuntimeError("ai_endpoint_empty")
        # intentional: simulate call failure path for tests when endpoint is "fail://"
        if str(endpoint).startswith("fail://"):
            raise RuntimeError("ai_forced_fail")
        # unknown endpoint → fail closed to rules
        raise RuntimeError("ai_not_configured")
    except Exception:
        return clean_title(title)


def expand_keywords(seed: str) -> list[str]:
    cfg = load_ai_cfg()
    if not cfg.get("enabled"):
        return [seed]
    try:
        if str(cfg.get("endpoint") or "").startswith("fail://"):
            raise RuntimeError("ai_forced_fail")
        return [seed]
    except Exception:
        return [seed]


def extract_buyer(text: str) -> str | None:
    cfg = load_ai_cfg()
    if not cfg.get("enabled"):
        return None
    try:
        if str(cfg.get("endpoint") or "").startswith("fail://"):
            raise RuntimeError("ai_forced_fail")
        return None
    except Exception:
        return None
