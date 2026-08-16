"""CRM from MySQL notices → entities table + HTML（主体名规范化 + 全国同名合并）."""
from __future__ import annotations

import json
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from db import connect  # noqa: E402

OUT_HTML = ROOT / "data" / "web" / "crm.html"
CFG = json.loads((ROOT / "config" / "crm_config.json").read_text(encoding="utf-8"))

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


def extract_entity(title: str) -> str | None:
    t = re.sub(r"\s+", "", title or "")
    t = re.split(r"(招标公告|采购公告|竞争性磋商|询比公告|谈判公告|中标|更正)", t)[0]
    suffixes = sorted(CFG.get("entity_suffixes") or ["公司", "医院", "大学", "局", "中心", "委员会"], key=len, reverse=True)
    best = None
    for suf in suffixes:
        idx = t.find(suf)
        if idx < 0:
            continue
        end = idx + len(suf)
        chunk = re.sub(r"^[\d\-—·\.、]+", "", t[max(0, end - 40) : end])
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
            s = s[: -len(suf)]
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


def main():
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, title, city, province, publish_date, created_at, source_id, buyer, keyword "
                "FROM notices WHERE clean_status IS NULL OR clean_status!='drop'"
            )
            notices = cur.fetchall()
    finally:
        conn.close()

    buckets: dict[str, list] = defaultdict(list)
    name_variants: dict[str, list[str]] = defaultdict(list)
    for n in notices:
        raw = (n.get("buyer") or "").strip() or extract_entity(n.get("title") or "")
        if not raw:
            continue
        key = normalize_entity_key(raw)
        if len(key) < 2:
            continue
        buckets[key].append(n)
        name_variants[key].append(raw)

    entities = []
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            # 全国同名：唯一键改为仅 name，避免同名多城拆条
            try:
                cur.execute("ALTER TABLE entities DROP INDEX uk_name_city")
            except Exception:
                pass
            try:
                cur.execute("ALTER TABLE entities ADD UNIQUE KEY uk_name (name)")
            except Exception:
                pass
            # 全量重建，去掉旧脏重复
            cur.execute("DELETE FROM entities")
            for key, hist in buckets.items():
                name = pick_display_name(name_variants[key])[:256]
                times = [parse_dt(h.get("publish_date") or h.get("created_at")) for h in hist]
                times = sorted([t for t in times if t])
                cities = [h.get("city") for h in hist if h.get("city")]
                city = max(set(cities), key=cities.count) if cities else None
                provs = [h.get("province") for h in hist if h.get("province")]
                province = max(set(provs), key=provs.count) if provs else None
                last = times[-1] if times else None
                next_hint = None
                if len(times) >= 2:
                    gaps = [(times[i] - times[i - 1]).days for i in range(1, len(times))]
                    gaps = [g for g in gaps if 0 < g < 900]
                    if gaps:
                        med = int(statistics.median(gaps))
                        next_hint = f"粗估间隔约{med}天；下次约{(last + timedelta(days=med)).date() if last else '-'}"
                tag_counter = Counter()
                for h in hist:
                    k = (h.get("keyword") or "").strip()
                    if k:
                        tag_counter[k] += 1
                service_tags = [{"k": k, "n": n} for k, n in tag_counter.most_common()]
                meta = {
                    "notice_ids": [h["id"] for h in hist[:50]],
                    "sources": list({h["source_id"] for h in hist}),
                    "norm_key": key,
                    "name_variants": sorted(set(name_variants[key]))[:20],
                    "service_tags": service_tags,
                }
                cur.execute(
                    "INSERT INTO entities (name, entity_type, city, province, notice_count, last_notice_at, next_bid_hint, meta_json) "
                    "VALUES (%s,'buyer',%s,%s,%s,%s,%s,%s) "
                    "ON DUPLICATE KEY UPDATE notice_count=VALUES(notice_count), last_notice_at=VALUES(last_notice_at), "
                    "next_bid_hint=VALUES(next_bid_hint), meta_json=VALUES(meta_json), "
                    "city=VALUES(city), province=VALUES(province)",
                    (
                        name,
                        city or "",
                        province,
                        len(hist),
                        last.strftime("%Y-%m-%d %H:%M:%S") if last else None,
                        next_hint,
                        json.dumps(meta, ensure_ascii=False),
                    ),
                )
                entities.append(
                    {
                        "name": name,
                        "city": city,
                        "province": province,
                        "notice_count": len(hist),
                        "last_notice_at": last.isoformat(timespec="seconds") if last else None,
                        "next_bid_hint": next_hint,
                        "service_tags": service_tags,
                    }
                )
    finally:
        conn.close()

    entities.sort(key=lambda x: -x["notice_count"])

    def _tags(e):
        tags = e.get("service_tags") or []
        return escape("、".join(f"{t['k']}×{t['n']}" for t in tags[:5]) or "-")

    rows = "".join(
        f"<tr><td>{escape(e['name'])}</td><td>{escape(e.get('city') or '-')}</td>"
        f"<td>{_tags(e)}</td><td>{e['notice_count']}</td><td>{escape(e.get('last_notice_at') or '-')}</td>"
        f"<td>{escape(e.get('next_bid_hint') or '-')}</td></tr>"
        for e in entities[:200]
    )
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"/><title>CRM主体</title>
<style>body{{font-family:Microsoft YaHei,sans-serif;margin:24px}}table{{border-collapse:collapse;width:100%}}
th,td{{border:1px solid #ddd;padding:8px;font-size:13px}}th{{background:#f3f4f6}}</style></head>
<body><h1>CRM 主体（规范化去重 / 全国同名合并）</h1><p>共 {len(entities)} 个主体</p>
<table><thead><tr><th>主体</th><th>主城</th><th>业务</th><th>公告数</th><th>最近公告</th><th>下次粗估</th></tr></thead>
<tbody>{rows or '<tr><td colspan=6>暂无</td></tr>'}</tbody></table></body></html>"""
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    summary = ROOT / "data" / "web" / "crm_summary.json"
    summary.write_text(json.dumps({"count": len(entities), "top": entities[:20]}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT_HTML, "entities", len(entities))


if __name__ == "__main__":
    main()
