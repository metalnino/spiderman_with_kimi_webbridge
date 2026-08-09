"""Cascade filter helpers for list/dashboard (pure functions for tests)."""
from __future__ import annotations


PROVINCE_CITY = {
    "江苏": ["南京", "苏州"],
    "上海": ["上海"],
    "浙江": ["杭州"],
    "广东": ["深圳"],
    "湖北": ["武汉"],
    "安徽": ["合肥"],
}


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
