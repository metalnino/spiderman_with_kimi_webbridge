from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def sources_cfg() -> dict:
    return load_json("config/sources.json")


def anti_bot_cfg() -> dict:
    return load_json("config/anti_bot.json")


def crawl_cfg() -> dict:
    return load_json("config/crawl_config.json")


def trial_keywords() -> list[str]:
    s = sources_cfg()
    kws = (s.get("defaults") or {}).get("trial_keywords")
    if kws:
        return list(kws)
    kd = crawl_cfg().get("keywords") or {}
    if isinstance(kd, dict):
        return list(kd.get("active") or kd.get("core") or [])[:5]
    return list(kd or [])[:5]


def cities() -> list[dict]:
    return list(crawl_cfg().get("cities") or [])


def target_city_names() -> list[str]:
    return [c["name"] for c in cities() if c.get("name")]


def only_target_cities() -> bool:
    return bool(crawl_cfg().get("only_target_cities"))


def publish_date_range() -> tuple[str | None, str | None]:
    r = crawl_cfg().get("publish_date_range") or {}
    return r.get("start"), r.get("end")
