"""HTTP list crawl with anti-bot delays; build filterable HTML viewer."""
from __future__ import annotations

import json
import random
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "config" / "crawl_config.json").read_text(encoding="utf-8"))
ANTI = json.loads((ROOT / "config" / "anti_bot.json").read_text(encoding="utf-8"))
OUT_DIR = ROOT / "data" / "trial"
OUT_DIR.mkdir(parents=True, exist_ok=True)

HTTP = ANTI.get("http") or {}
TIMEOUT = int(HTTP.get("timeout_sec") or 20)
RETRIES = int(HTTP.get("retries") or 2)
DELAY_MIN = float(HTTP.get("delay_ms_min") or 400) / 1000.0
DELAY_MAX = float(HTTP.get("delay_ms_max") or 1600) / 1000.0

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
CITIES = [c["name"] for c in CFG["cities"]]
DETAIL_TMPL = CFG["source"]["detail_url_template"]
NOW = datetime.now()


def sleep_jitter() -> None:
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


def fetch(url: str) -> str:
    last = None
    for i in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
            for enc in ("utf-8", "gbk", "gb2312"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.6 * (i + 1))
    raise RuntimeError(str(last))


def build_url(keyword: str, area_code: str, page: int = 1) -> str:
    src = CFG["source"]
    q = {
        "searchDate": time.strftime("%Y-%m-%d"),
        "dates": src["dates"],
        "word": keyword,
        "categoryId": src["category_id"],
        "industryName": "",
        "area": area_code,
        "status": "",
        "publishMedia": "",
        "sourceInfo": "",
        "showStatus": src["show_status"],
        "page": str(page),
    }
    return src["list_url"] + "?" + urllib.parse.urlencode(q, encoding="utf-8")


ROW_RE = re.compile(
    r"<tr>\s*<td[^>]*name=\"imgShow\"[^>]*id=\"([^\"]*)\"[^>]*>\s*"
    r"<a href=\"javascript:urlOpen\('([0-9a-fA-F]{16,})'\)\"[^>]*title=\"([^\"]*)\"[\s\S]*?</a>"
    r"[\s\S]*?<span title\s*=\s*\"([^\"]*)\">\s*([^<]*)</span>"
    r"[\s\S]*?<span title\s*=\s*\"([^\"]*)\">\s*([^<]*)</span>"
    r"[\s\S]*?<td>([^<]*)</td>\s*<td>\s*([^<]*?)\s*</td>\s*"
    r"<td name=\"openTime\" id=\"([^\"]*)\"",
    re.I,
)


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


def attach_status(item: dict) -> dict:
    ot = parse_dt(item.get("open_time"))
    if not ot:
        item.update({"bid_status": "未知", "bid_status_code": "unknown", "days_to_open": None})
        return item
    if ot > NOW:
        item.update(
            {
                "bid_status": "可投标/未开标",
                "bid_status_code": "open",
                "days_to_open": max(0, int((ot - NOW).total_seconds() // 86400)),
            }
        )
    else:
        item.update({"bid_status": "已开标", "bid_status_code": "closed", "days_to_open": 0})
    return item


def parse_rows(html: str) -> list[dict]:
    rows = []
    for m in ROW_RE.finditer(html):
        publish_dt, uuid, title, industry_title, industry, region_title, region, source, pub_date, open_time = m.groups()
        title = re.sub(r"\s+", " ", unescape(title)).strip()
        industry = re.sub(r"\s+", " ", unescape(industry)).strip() or industry_title.strip()
        region = re.sub(r"\s+", " ", unescape(region)).strip() or region_title.strip()
        region = region.replace("【", "").replace("】", "")
        source = re.sub(r"\s+", " ", unescape(source)).strip()
        pub_date = pub_date.strip()
        open_time = open_time.strip()
        publish_time = publish_dt.strip() or (pub_date + " 00:00:00" if pub_date else "")
        rows.append(
            {
                "uuid": uuid,
                "title": title,
                "industry": industry,
                "region": region_title.strip() or region,
                "source": source,
                "publish_date": pub_date,
                "publish_time": publish_time,
                "open_time": open_time if open_time and open_time != "null" else "",
                "amount": None,
                "amount_text": "",
                "official_url": DETAIL_TMPL.format(uuid=uuid),
            }
        )
    return rows


CITY_TO_PROVINCE = {c["name"]: c["province"] for c in CFG["cities"]}


def match_cities(title: str, region: str, province: str) -> list[str]:
    """Prefer cities mentioned in title (project location). Do not trust site region alone."""
    hits = [c for c in CITIES if c in title]
    # Only if title has no city: shanghai municipality fallback
    if not hits and (province == "上海" or region in ("上海", "上海市")):
        hits.append("上海")
    return hits


def active_keywords() -> list[str]:
    kws = CFG.get("keywords")
    if isinstance(kws, dict):
        return list(kws.get("active") or kws.get("core") or [])
    return list(kws or [])


def collect() -> list[dict]:
    province_codes = {}
    for c in CFG["cities"]:
        province_codes.setdefault(c["area_code"], c["province"])

    kws = active_keywords()
    total = len(kws) * len(province_codes)
    done = 0
    items = []
    errors = 0
    print(f"[plan] keywords={len(kws)} provinces={len(province_codes)} requests={total}", flush=True)

    for kw in kws:
        for area_code, province in province_codes.items():
            done += 1
            url = build_url(kw, area_code, 1)
            try:
                html = fetch(url)
                rows = parse_rows(html)
                err = None
            except Exception as e:  # noqa: BLE001
                rows, err = [], str(e)
                errors += 1
            print(f"[fetch {done}/{total}] {kw}|{province} -> {len(rows)} err={err}", flush=True)
            for r in rows:
                cities = match_cities(r["title"], r["region"], province)
                if not cities:
                    continue
                for city in cities:
                    items.append(attach_status({**r, "keyword": kw, "province": province, "city": city}))
            sleep_jitter()

    seen = set()
    out = []
    for r in items:
        key = (r["uuid"], r["city"], r["keyword"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    print(f"[done] items={len(out)} errors={errors}", flush=True)
    return out


HTML_TMPL = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>绿植招标试爬结果</title>
<style>
  :root { --bg:#f3f1eb; --panel:#fffdf8; --ink:#1c2430; --muted:#5d6b7a; --line:#d9d2c5; --accent:#0f6a4f; --accent-2:#c45c26; }
  *{box-sizing:border-box}
  body{margin:0;font-family:"Noto Sans SC","Segoe UI",sans-serif;color:var(--ink);background:radial-gradient(900px 400px at 10% -10%,#e7f2ec,transparent 55%),var(--bg)}
  .wrap{max-width:1180px;margin:0 auto;padding:28px 18px 48px}
  h1{margin:0 0 6px;font-size:28px}
  .sub{color:var(--muted);margin-bottom:18px;font-size:14px}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:14px}
  .filters{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:10px}
  label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted)}
  input,select,button{font:inherit;border:1px solid var(--line);border-radius:8px;padding:8px 10px;background:#fff;color:var(--ink)}
  button{background:var(--accent);color:#fff;border-color:var(--accent);cursor:pointer}
  button.ghost{background:#fff;color:var(--ink)}
  .meta{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;color:var(--muted);font-size:13px;margin:8px 2px 0}
  table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
  th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-size:13px}
  th{background:#f0ebe2;font-size:12px;color:var(--muted);font-weight:600}
  .title{font-weight:600;line-height:1.35}.muted{color:var(--muted)}
  a.link{color:var(--accent-2);text-decoration:none;font-weight:600;white-space:nowrap}
  .pager{display:flex;gap:8px;align-items:center;justify-content:center;margin-top:14px}
  .pager button[disabled]{opacity:.45;cursor:not-allowed}
  .tag{display:inline-block;padding:2px 7px;border-radius:999px;background:#e8f3ee;color:var(--accent);font-size:12px;margin-right:4px}
  @media(max-width:960px){.filters{grid-template-columns:1fr 1fr}.hide-sm{display:none}}
</style>
</head>
<body>
  <div class="wrap">
    <h1>绿植招标试爬结果</h1>
    <div class="sub">HTTP 列表爬取 · 随机间隔防封 · 金额待详情验证码后补 · 「看详情」可能需验证</div>
    <div class="panel">
      <div class="filters">
        <label>城市<select id="city"></select></label>
        <label>关键词<select id="keyword"></select></label>
        <label>省份<select id="province"></select></label>
        <label>投标状态
          <select id="bidStatus">
            <option value="">全部状态</option>
            <option value="open" selected>可投标/未开标</option>
            <option value="closed">已开标</option>
            <option value="unknown">未知</option>
          </select>
        </label>
        <label>标题包含<input id="q" placeholder="搜索标题" /></label>
        <label>排序
          <select id="sort">
            <option value="publish_time_desc">发布时间新→旧</option>
            <option value="publish_time_asc">发布时间旧→新</option>
            <option value="open_time_desc">开标时间新→旧</option>
            <option value="open_time_asc">开标时间旧→新</option>
            <option value="amount_desc">金额高→低</option>
            <option value="amount_asc">金额低→高</option>
          </select>
        </label>
        <label>每页
          <select id="pageSize"><option>10</option><option selected>20</option><option>50</option></select>
        </label>
      </div>
      <div class="meta"><div id="stats"></div><div><button class="ghost" id="resetBtn" type="button">重置</button></div></div>
    </div>
    <table>
      <thead>
        <tr>
          <th style="width:40%">标题</th><th>城市</th><th class="hide-sm">关键词</th><th class="hide-sm">地区</th>
          <th>发布</th><th>开标</th><th>状态</th><th>金额</th><th>详情</th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
    <div class="pager">
      <button id="prev" type="button">上一页</button>
      <span id="pageInfo" class="muted"></span>
      <button id="next" type="button">下一页</button>
    </div>
  </div>
<script>
const DATA = __DATA__;
let page = 1;
function uniq(key){return [...new Set(DATA.map(x=>x[key]).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh'));}
function fillSelect(id, values, allLabel){document.getElementById(id).innerHTML=`<option value="">${allLabel}</option>`+values.map(v=>`<option value="${v}">${v}</option>`).join('');}
fillSelect('city', uniq('city'), '全部城市');
fillSelect('keyword', uniq('keyword'), '全部关键词');
fillSelect('province', uniq('province'), '全部省份');
function parseTime(s){if(!s)return null;const t=Date.parse(String(s).replace(/-/g,'/'));return Number.isNaN(t)?null:t;}
function cmpNullable(a,b,asc){if(a==null&&b==null)return 0;if(a==null)return 1;if(b==null)return -1;return asc?(a-b):(b-a);}
const citySel=document.getElementById('city'), keywordSel=document.getElementById('keyword'), provinceSel=document.getElementById('province');
const bidStatusSel=document.getElementById('bidStatus'), qInput=document.getElementById('q'), sortSel=document.getElementById('sort');
const pageSizeSel=document.getElementById('pageSize'), tbody=document.getElementById('tbody'), stats=document.getElementById('stats');
const pageInfo=document.getElementById('pageInfo'), prevBtn=document.getElementById('prev'), nextBtn=document.getElementById('next');
function filtered(){
  const city=citySel.value, keyword=keywordSel.value, province=provinceSel.value, bidStatus=bidStatusSel.value, q=qInput.value.trim();
  let rows=DATA.filter(r=>{
    if(city&&r.city!==city)return false;
    if(keyword&&r.keyword!==keyword)return false;
    if(province&&r.province!==province)return false;
    if(bidStatus&&r.bid_status_code!==bidStatus)return false;
    if(q&&!(r.title||'').includes(q))return false;
    return true;
  });
  const sort=sortSel.value;
  rows.sort((a,b)=>{
    if(sort.startsWith('publish_time'))return cmpNullable(parseTime(a.publish_time||a.publish_date),parseTime(b.publish_time||b.publish_date),sort.endsWith('asc'));
    if(sort.startsWith('open_time'))return cmpNullable(parseTime(a.open_time),parseTime(b.open_time),sort.endsWith('asc'));
    if(sort.startsWith('amount'))return cmpNullable(a.amount,b.amount,sort.endsWith('asc'));
    return 0;
  });
  return rows;
}
function render(){
  const rows=filtered(); const size=Number(pageSizeSel.value)||20;
  const pages=Math.max(1,Math.ceil(rows.length/size)); if(page>pages)page=pages; if(page<1)page=1;
  const slice=rows.slice((page-1)*size, page*size);
  tbody.innerHTML=slice.map(r=>`<tr>
    <td><div class="title">${escapeHtml(r.title)}</div><div class="muted" style="margin-top:4px">${escapeHtml(r.source||'')}</div></td>
    <td><span class="tag">${escapeHtml(r.city||'')}</span></td>
    <td class="hide-sm">${escapeHtml(r.keyword||'')}</td>
    <td class="hide-sm">${escapeHtml(r.region||r.province||'')}</td>
    <td>${escapeHtml(r.publish_date||'-')}</td>
    <td>${escapeHtml((r.open_time||'').slice(0,16)||'-')}</td>
    <td>${escapeHtml(r.bid_status||'-')}${r.bid_status_code==='open'&&r.days_to_open!=null?` <span class="muted">(${r.days_to_open}天)</span>`:''}</td>
    <td>${r.amount==null?'<span class="muted">待补</span>':escapeHtml(String(r.amount_text||r.amount))}</td>
    <td><a class="link" href="${escapeAttr(r.official_url)}" target="_blank" rel="noopener" title="可能需验证码">看详情</a></td>
  </tr>`).join('')||`<tr><td colspan="9" class="muted">无匹配结果</td></tr>`;
  stats.textContent=`共 ${rows.length} 条 / 全量 ${DATA.length} 条 · 第 ${page}/${pages} 页`;
  pageInfo.textContent=`${page} / ${pages}`; prevBtn.disabled=page<=1; nextBtn.disabled=page>=pages;
}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function escapeAttr(s){return escapeHtml(s);}
[citySel,keywordSel,provinceSel,bidStatusSel,sortSel,pageSizeSel].forEach(el=>el.addEventListener('change',()=>{page=1;render();}));
qInput.addEventListener('input',()=>{page=1;render();});
prevBtn.addEventListener('click',()=>{page--;render();}); nextBtn.addEventListener('click',()=>{page++;render();});
document.getElementById('resetBtn').addEventListener('click',()=>{citySel.value='';keywordSel.value='';provinceSel.value='';bidStatusSel.value='open';qInput.value='';sortSel.value='publish_time_desc';pageSizeSel.value='20';page=1;render();});
render();
</script>
</body>
</html>
"""


def main() -> None:
    items = collect()
    (OUT_DIR / "items_enriched.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    open_n = sum(1 for x in items if x.get("bid_status_code") == "open")
    summary = {
        "count": len(items),
        "open": open_n,
        "closed": sum(1 for x in items if x.get("bid_status_code") == "closed"),
        "unique_uuid": len({x["uuid"] for x in items}),
        "html": str(OUT_DIR / "viewer.html"),
    }
    (OUT_DIR / "crawl_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    html = HTML_TMPL.replace("__DATA__", json.dumps(items, ensure_ascii=False))
    (OUT_DIR / "viewer.html").write_text(html, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
