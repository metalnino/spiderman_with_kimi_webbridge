from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(rel: str):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def platform_overrides() -> dict:
    """员工外壳配置层 config/platforms.json（platformConfig[]，契约 collector/v1.0.0）。

    只把 params（selector 等内核参数）展开为 {平台id: {...}} 覆盖到 sources.json 底座。
    enabled/name/route/proxy 是外壳层元数据，不泄漏进内核配置（避免影响 NAS/调度器的
    源站启用口径）。文件不存在/解析失败时返回空 dict，内核行为与未套壳时完全一致。"""
    p = ROOT / "config" / "platforms.json"
    if not p.exists():
        return {}
    try:
        entries = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict = {}
    for entry in entries or []:
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        params = entry.get("params")
        if isinstance(params, dict) and params:
            out[str(entry["id"])] = dict(params)
    return out


def sources_cfg() -> dict:
    cfg = load_json("config/sources.json")
    # 契约配置层 platforms.json 覆盖底座 sources.json（selector 改版时改进层只改 platforms.json）
    for pid, extra in platform_overrides().items():
        cfg.setdefault(pid, {}).update(extra)
    return cfg


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
