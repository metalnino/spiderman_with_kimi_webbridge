"""Shared HTTP helpers for multi-site crawlers."""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sleep_jitter(ms_min: int = 600, ms_max: int = 1800):
    time.sleep(random.uniform(ms_min / 1000, ms_max / 1000))


def fetch_bytes(url: str, *, data=None, headers=None, timeout=30, retries=2):
    hdrs = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        hdrs.update(headers)
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, data=data, headers=hdrs, method="POST" if data else "GET")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.5 * (i + 1))
    raise RuntimeError(f"fetch failed: {url} ({last})")


def fetch_text(url: str, **kwargs) -> str:
    _, raw, _ = fetch_bytes(url, **kwargs)
    for enc in ("utf-8", "gbk", "gb2312"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def fetch_json(url: str, **kwargs):
    _, raw, _ = fetch_bytes(url, **kwargs)
    return json.loads(raw.decode("utf-8", "ignore"))


def active_cities():
    cfg = load_json(ROOT / "config" / "crawl_config.json")
    return list(cfg.get("cities") or [])


def trial_keywords(sources_cfg: dict | None = None) -> list[str]:
    if sources_cfg is None:
        sources_cfg = load_json(ROOT / "config" / "sources.json")
    kws = (sources_cfg.get("defaults") or {}).get("trial_keywords")
    if kws:
        return list(kws)
    crawl = load_json(ROOT / "config" / "crawl_config.json")
    kd = crawl.get("keywords") or {}
    if isinstance(kd, dict):
        return list(kd.get("active") or kd.get("core") or [])[:5]
    return list(kd or [])[:5]


def match_cities(title: str, cities: list[dict], province_name: str | None = None) -> list[str]:
    hits = [c["name"] for c in cities if c["name"] in title]
    if province_name == "上海" and "上海" not in hits:
        hits.append("上海")
    # province-level soft hit: keep if title has province and city is in that province
    if not hits and province_name:
        for c in cities:
            if c.get("province") == province_name and province_name in title:
                hits.append(c["name"])
                break
    return hits


def province_code_map(cities: list[dict]) -> dict[str, str]:
    """area_code -> province name"""
    m = {}
    for c in cities:
        m[c["area_code"]] = c["province"]
    return m
