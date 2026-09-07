"""实体（采购人/招标人主体）聚合与招标周期粗估。纯函数，无 DB/网络。

从 scripts/jobs/build_crm_db.py 提炼的可复用规范：
  主体名规范化 → 全国同名合并 → 历史周期中位间隔 → 下次招标粗估（hint，非事实）。

周期粗估是启发式（确定性规则），不是预测承诺：样本 < min_history_for_estimate 时如实返回空。
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
_CFG_PATH = ROOT / "config" / "crm_config.json"

# 合并用：去掉后比较的公司形态后缀（长的优先）
_NORM_STRIP_SUFFIXES = (
    "股份有限公司",
    "有限责任公司",
    "有限公司",
    "集团有限公司",
    "集团公司",
    "集团",
    "分公司",
    "支公司",
)


def _load_cfg() -> dict:
    try:
        return json.loads(_CFG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _norm_title(t: str | None) -> str:
    """跨站折叠用的标题规范化：去空白/全角空格/制表符/不换行空格。"""
    return re.sub(r"[\s\u3000\t\u00a0]", "", t or "")


def extract_entity(title: str) -> str | None:
    """标题 → 主体名兜底（buyer 缺失时）。"""
    cfg = _load_cfg()
    t = re.sub(r"\s+", "", title or "")
    t = re.split(r"(招标公告|采购公告|竞争性磋商|询比公告|谈判公告|中标|成交|更正)", t)[0]
    suffixes = sorted(
        cfg.get("entity_suffixes") or ["公司", "医院", "大学", "局", "中心", "委员会"],
        key=len,
        reverse=True,
    )
    best = None
    for suf in suffixes:
        idx = t.find(suf)
        if idx < 0:
            continue
        end = idx + len(suf)
        chunk = re.sub(r"^[\d\-—·\.、]+", "", t[max(0, end - 40):end])
        if len(chunk) >= 4 and (best is None or len(chunk) > len(best)):
            best = chunk
    return best


def normalize_entity_key(name: str) -> str:
    """全国合并键：去空白/括号噪声，统一常见公司后缀。"""
    s = (name or "").strip()
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"[\(（][^\)）]{0,40}[\)）]", "", s)
    s = s.replace("株式会社", "").replace("有限责任", "有限")
    for suf in _NORM_STRIP_SUFFIXES:
        if s.endswith(suf) and len(s) > len(suf) + 2:
            s = s[:-len(suf)]
            break
    return s.casefold()


def pick_display_name(names: list[str]) -> str:
    """展示名取最长且含「公司/院/局」等更完整写法。"""
    uniq = [n for n in names if n]
    if not uniq:
        return ""
    return sorted(uniq, key=lambda x: (len(x), x), reverse=True)[0]


def parse_dt(s) -> datetime | None:
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    s = str(s).replace("T", " ")
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:n], fmt)
        except ValueError:
            continue
    return None


def estimate_next_bid(times: list[datetime]) -> dict:
    """历史发布时间 → 下次招标粗估。

    返回 {hint, median_days, next_date, confidence}；样本不足/无有效间隔时全 None。
    confidence: low(<4 样本)/medium(4-6)/high(>=7)。粗估是提示，不是事实。
    """
    cfg = _load_cfg()
    min_n = int(cfg.get("min_history_for_estimate") or 2)
    times = sorted([t for t in times if t])
    if len(times) < min_n:
        return {"hint": None, "median_days": None, "next_date": None, "confidence": None}
    gaps = [(times[i] - times[i - 1]).days for i in range(1, len(times))]
    gaps = [g for g in gaps if 0 < g < 900]
    if not gaps:
        return {"hint": None, "median_days": None, "next_date": None, "confidence": None}
    med = int(median(gaps))
    last = times[-1]
    next_date = last + timedelta(days=med)
    n = len(gaps) + 1
    confidence = "high" if n >= 7 else ("medium" if n >= 4 else "low")
    hint = f"粗估间隔约{med}天；下次约{next_date.date()}"
    return {
        "hint": hint,
        "median_days": med,
        "next_date": next_date.strftime("%Y-%m-%d"),
        "confidence": confidence,
    }


def aggregate_entities(notices: list[dict]) -> list[dict]:
    """notice dicts → 实体列表（契约 output.entities 同构）。

    每条 notice 需含：title, city, province, publish_date, created_at, buyer,
    keyword, source_id, original_url, origin_source, id。
    """
    buckets: dict[str, list[dict]] = defaultdict(list)
    variants: dict[str, list[str]] = defaultdict(list)
    for n in notices:
        raw = (n.get("buyer") or "").strip() or extract_entity(n.get("title") or "")
        if not raw:
            continue
        key = normalize_entity_key(raw)
        if len(key) < 2:
            continue
        buckets[key].append(n)
        variants[key].append(raw)

    entities: list[dict] = []
    for key, hist in buckets.items():
        name = pick_display_name(variants[key])[:256]
        folded = len({(_norm_title(h.get("title")), h.get("city") or "") for h in hist})
        times = sorted(
            t for t in (parse_dt(h.get("publish_date") or h.get("created_at")) for h in hist) if t
        )
        cities = [h.get("city") for h in hist if h.get("city")]
        provs = [h.get("province") for h in hist if h.get("province")]
        city = max(set(cities), key=cities.count) if cities else None
        province = max(set(provs), key=provs.count) if provs else None
        last = times[-1] if times else None
        est = estimate_next_bid(times)
        tags = Counter((h.get("keyword") or "").strip() for h in hist if (h.get("keyword") or "").strip())
        channels = sorted({u for h in hist for u in [h.get("original_url")] if u})
        origins = sorted({o for h in hist for o in [h.get("origin_source")] if o})
        entities.append({
            "name": name,
            "entityType": "buyer",
            "city": city,
            "province": province,
            "noticeCount": folded,
            "lastNoticeAt": last.strftime("%Y-%m-%dT%H:%M:%S") if last else None,
            "nextBidHint": est["hint"],
            "nextBidConfidence": est["confidence"],
            "medianCycleDays": est["median_days"],
            "nextBidDate": est["next_date"],
            "officialChannels": channels,
            "originSources": origins,
            "serviceTags": [{"k": k, "n": v} for k, v in tags.most_common()],
            "noticeIds": [h.get("id") for h in hist[:50] if h.get("id") is not None],
        })
    entities.sort(key=lambda e: -(e["noticeCount"] or 0))
    return entities
