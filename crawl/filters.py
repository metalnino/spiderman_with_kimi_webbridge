"""Cascade filter helpers for list/dashboard."""
from __future__ import annotations

from crawl.config_loader import cities as _cfg_cities


def _build_province_city() -> dict[str, list[str]]:
    m: dict[str, list[str]] = {}
    for c in _cfg_cities():
        prov = c.get("province")
        name = c.get("name")
        if prov and name and name not in m.setdefault(prov, []):
            m[prov].append(name)
    return m


# 省→市 单一配置源：来自 config/crawl_config.json 的 cities
PROVINCE_CITY = _build_province_city()


def cities_for_province(province: str | None) -> list[str]:
    if not province:
        return []
    return list(PROVINCE_CITY.get(province, []))


def reset_city_when_province_changes(prev_province: str | None, new_province: str | None, city: str | None) -> str | None:
    """Cascade rule: province change clears city unless still valid."""
    if prev_province == new_province:
        return city
    allowed = cities_for_province(new_province)
    if city and city in allowed:
        return city
    return None


def source_capability_hint(source_id: str) -> str | None:
    if source_id == "chinabidding":
        return "采招网列表可见；金额/招标人等详情需登录，当前无金额字段"
    if source_id == "cebpub":
        return "详情可能需验证码；列表字段可用"
    return None


def apply_filters(
    rows: list[dict],
    *,
    source_ids: list[str] | None = None,
    province: str | None = None,
    city: str | None = None,
    keyword: str | None = None,
    only_pass: bool = False,
    exclude_irrelevant: bool = True,
) -> list[dict]:
    out = []
    for r in rows:
        if source_ids and r.get("source_id") not in source_ids:
            continue
        if province and (r.get("province") or "") != province and province not in (r.get("region_text") or ""):
            # soft: title/city province map
            if r.get("city") not in cities_for_province(province):
                continue
        if city and r.get("city") != city:
            continue
        if keyword and r.get("keyword") != keyword and keyword not in (r.get("title") or ""):
            continue
        if only_pass and r.get("clean_status") == "drop":
            continue
        if exclude_irrelevant and r.get("manual_label") == "irrelevant":
            continue
        out.append(r)
    return out
