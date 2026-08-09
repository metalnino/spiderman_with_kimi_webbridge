"""Build a lightweight CRM layer: entities, bid history, next-bid estimate."""
from __future__ import annotations

import json
import re
import statistics
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config" / "crm_config.json").read_text(encoding="utf-8"))
ITEMS_PATH = ROOT / "data" / "trial" / "items_enriched.json"
OUT_DIR = ROOT / "data" / "crm"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    s = str(s).strip().replace("T", " ")
    for fmt, n in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(s[:n], fmt)
        except ValueError:
            continue
    return None


def extract_entity(title: str) -> str | None:
    t = re.sub(r"\s+", "", title)
    # cut common tender suffixes
    t = re.split(r"(招标公告|采购公告|竞争性磋商|询比公告|谈判公告|中标|更正)", t)[0]
    suffixes = sorted(CFG["entity_suffixes"], key=len, reverse=True)
    best = None
    for suf in suffixes:
        idx = t.find(suf)
        if idx < 0:
            continue
        end = idx + len(suf)
        start = max(0, end - 40)
        chunk = t[start:end]
        # prefer longest meaningful chunk ending with suffix
        # trim leading junk digits/punct
        chunk = re.sub(r"^[\d\-—·\.、]+", "", chunk)
        if len(chunk) >= 4:
            if best is None or len(chunk) > len(best):
                best = chunk
    if best:
        return best
    # fallback: leading org-like segment before 关于/项目
    m = re.match(r"(.{4,30}?)(关于|项目|采购|服务)", t)
    if m:
        return m.group(1)
    return None


def event_time(item: dict) -> datetime | None:
    return parse_dt(item.get("open_time")) or parse_dt(item.get("publish_time")) or parse_dt(item.get("publish_date"))


def build(items: list[dict]) -> dict:
    buckets: dict[str, list[dict]] = {}
    unmatched = 0
    for it in items:
        name = extract_entity(it.get("title") or "")
        if not name:
            unmatched += 1
            continue
        buckets.setdefault(name, []).append(it)

    entities = []
    for name, hist in buckets.items():
        # unique by uuid
        by_uuid = {}
        for h in hist:
            by_uuid[h["uuid"]] = h
        hist_u = list(by_uuid.values())
        timed = []
        for h in hist_u:
            dt = event_time(h)
            if dt:
                timed.append((dt, h))
        timed.sort(key=lambda x: x[0])
        times = [x[0] for x in timed]
        gaps = [(times[i] - times[i - 1]).days for i in range(1, len(times)) if (times[i] - times[i - 1]).days > 0]
        median_gap = int(statistics.median(gaps)) if gaps else None
        last = times[-1] if times else None
        cycle = median_gap if median_gap and median_gap >= 30 else (CFG["default_cycle_days"] if last else None)
        next_est = (last + timedelta(days=cycle)) if last and cycle else None
        cities = sorted({h.get("city") for h in hist_u if h.get("city")})
        keywords = sorted({h.get("keyword") for h in hist_u if h.get("keyword")})
        entities.append(
            {
                "name": name,
                "cities": cities,
                "keywords": keywords,
                "bid_count": len(hist_u),
                "first_seen": times[0].strftime("%Y-%m-%d") if times else None,
                "last_seen": last.strftime("%Y-%m-%d") if last else None,
                "median_cycle_days": median_gap,
                "estimate_cycle_days": cycle,
                "next_bid_estimate": next_est.strftime("%Y-%m-%d") if next_est else None,
                "confidence": (
                    "high" if gaps and len(gaps) >= 2 else ("medium" if gaps else "low")
                ),
                "history": [
                    {
                        "uuid": h["uuid"],
                        "title": h["title"],
                        "city": h.get("city"),
                        "keyword": h.get("keyword"),
                        "publish_date": h.get("publish_date"),
                        "open_time": h.get("open_time"),
                        "official_url": h.get("official_url"),
                    }
                    for _, h in timed
                ]
                or [
                    {
                        "uuid": h["uuid"],
                        "title": h["title"],
                        "city": h.get("city"),
                        "keyword": h.get("keyword"),
                        "publish_date": h.get("publish_date"),
                        "open_time": h.get("open_time"),
                        "official_url": h.get("official_url"),
                    }
                    for h in hist_u
                ],
            }
        )

    entities.sort(key=lambda e: (e["next_bid_estimate"] or "9999", -(e["bid_count"])))
    return {
        "summary": {
            "source_items": len(items),
            "entities": len(entities),
            "unmatched_titles": unmatched,
            "with_estimate": sum(1 for e in entities if e["next_bid_estimate"]),
            "high_confidence": sum(1 for e in entities if e["confidence"] == "high"),
        },
        "entities": entities,
    }


HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>招标主体 CRM（试跑）</title>
<style>
  :root { --bg:#f3f1eb; --panel:#fffdf8; --ink:#1c2430; --muted:#5d6b7a; --line:#d9d2c5; --accent:#0f6a4f; --warn:#c45c26; }
  body{margin:0;font-family:"Noto Sans SC","Segoe UI",sans-serif;color:var(--ink);background:radial-gradient(800px 360px at 0% 0%,#e7f2ec,transparent 50%),var(--bg)}
  .wrap{max-width:1100px;margin:0 auto;padding:28px 16px 48px}
  h1{margin:0 0 6px;font-size:26px} .sub{color:var(--muted);margin-bottom:14px;font-size:13px}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px;margin-bottom:12px;display:grid;grid-template-columns:repeat(4,1fr);gap:8px}
  label{font-size:12px;color:var(--muted);display:flex;flex-direction:column;gap:4px}
  input,select{font:inherit;padding:8px;border:1px solid var(--line);border-radius:8px}
  table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}
  th,td{padding:10px;border-bottom:1px solid var(--line);font-size:13px;vertical-align:top;text-align:left}
  th{background:#f0ebe2;color:var(--muted);font-size:12px}
  .tag{display:inline-block;background:#e8f3ee;color:var(--accent);padding:2px 6px;border-radius:999px;font-size:12px;margin:0 3px 3px 0}
  .low{color:#9a6b00}.med{color:var(--warn)}.high{color:var(--accent)}
  a{color:var(--warn);font-weight:600;text-decoration:none}
  .meta{color:var(--muted);font-size:13px;margin:8px 0}
  @media(max-width:800px){.panel{grid-template-columns:1fr 1fr}}
</style>
</head>
<body>
<div class="wrap">
  <h1>招标主体 CRM（试跑）</h1>
  <div class="sub">记录主体 · 历史标讯 · 预估下次招标时间（中位间隔；样本少则默认 365 天）</div>
  <div class="panel">
    <label>城市<select id="city"></select></label>
    <label>置信度<select id="conf"><option value="">全部</option><option>high</option><option>medium</option><option>low</option></select></label>
    <label>主体包含<input id="q" placeholder="搜主体名"></label>
    <label>排序<select id="sort"><option value="next">下次预估近→远</option><option value="count">标讯数多→少</option><option value="last">最近出现</option></select></label>
  </div>
  <div class="meta" id="stats"></div>
  <table>
    <thead><tr><th>主体</th><th>城市</th><th>标讯</th><th>最近</th><th>周期(天)</th><th>下次预估</th><th>置信</th><th>最近官网</th></tr></thead>
    <tbody id="tbody"></tbody>
  </table>
</div>
<script>
const DATA = __DATA__;
const ents = DATA.entities;
function uniq(arr){return [...new Set(arr.filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh'))}
const citySel=document.getElementById('city');
citySel.innerHTML='<option value="">全部城市</option>'+uniq(ents.flatMap(e=>e.cities||[])).map(c=>`<option>${c}</option>`).join('');
const q=document.getElementById('q'), conf=document.getElementById('conf'), sort=document.getElementById('sort'), tbody=document.getElementById('tbody'), stats=document.getElementById('stats');
function render(){
  let rows=ents.filter(e=>{
    if(citySel.value && !(e.cities||[]).includes(citySel.value)) return false;
    if(conf.value && e.confidence!==conf.value) return false;
    if(q.value.trim() && !(e.name||'').includes(q.value.trim())) return false;
    return true;
  });
  rows=[...rows].sort((a,b)=>{
    if(sort.value==='count') return (b.bid_count||0)-(a.bid_count||0);
    if(sort.value==='last') return String(b.last_seen||'').localeCompare(String(a.last_seen||''));
    return String(a.next_bid_estimate||'9999').localeCompare(String(b.next_bid_estimate||'9999'));
  });
  stats.textContent=`显示 ${rows.length} / 主体 ${DATA.summary.entities} · 可预估 ${DATA.summary.with_estimate} · 高置信 ${DATA.summary.high_confidence}`;
  tbody.innerHTML=rows.map(e=>{
    const last= (e.history&&e.history[0]) ? e.history[e.history.length-1] : null;
    const url=last&&last.official_url ? last.official_url : '#';
    return `<tr>
      <td><strong>${esc(e.name)}</strong><div style="color:#5d6b7a;margin-top:4px">${(e.keywords||[]).map(k=>`<span class="tag">${esc(k)}</span>`).join('')}</div></td>
      <td>${(e.cities||[]).map(c=>`<span class="tag">${esc(c)}</span>`).join('')}</td>
      <td>${e.bid_count}</td>
      <td>${esc(e.last_seen||'-')}</td>
      <td>${e.estimate_cycle_days??'-'}</td>
      <td>${esc(e.next_bid_estimate||'-')}</td>
      <td class="${esc(e.confidence)}">${esc(e.confidence)}</td>
      <td>${last?`<a href="${esc(url)}" target="_blank" rel="noopener">转官网</a>`:'-'}</td>
    </tr>`}).join('')||'<tr><td colspan="8">无结果</td></tr>';
}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
[citySel,conf,sort].forEach(el=>el.addEventListener('change',render));
q.addEventListener('input',render);
render();
</script>
</body></html>
"""


def main() -> None:
    if not ITEMS_PATH.exists():
        raise SystemExit(f"missing {ITEMS_PATH}")
    items = json.loads(ITEMS_PATH.read_text(encoding="utf-8"))
    crm = build(items)
    (OUT_DIR / "entities.json").write_text(json.dumps(crm, ensure_ascii=False, indent=2), encoding="utf-8")
    html = HTML.replace("__DATA__", json.dumps(crm, ensure_ascii=False))
    out = OUT_DIR / "crm.html"
    out.write_text(html, encoding="utf-8")
    print(json.dumps({"summary": crm["summary"], "html": str(out)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
