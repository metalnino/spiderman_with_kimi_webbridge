"""Fix city/region display mismatch and rebuild clearer viewer."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "trial" / "items_relevant.json"
OUT_ITEMS = ROOT / "data" / "trial" / "items_relevant.json"
OUT_HTML = ROOT / "data" / "trial" / "viewer_relevant.html"
CFG = json.loads((ROOT / "config" / "crawl_config.json").read_text(encoding="utf-8"))

CITIES = [c["name"] for c in CFG["cities"]]
CITY_TO_PROVINCE = {c["name"]: c["province"] for c in CFG["cities"]}

# known source portals (best-effort)
SOURCE_URLS = {
    "江苏省招标投标公共服务平台": "http://www.jszbtb.com/",
    "上海市公共资源交易平台": "https://www.shggzy.com/",
    "浙江省招标投标公共服务平台": "https://zjztbpubservice.cnztb.com/",
    "广东省招标投标监管网": "https://zbtb.gd.gov.cn/",
    "湖北公共资源交易中心": "https://www.hbggzyfwpt.cn/",
    "安徽省招标投标信息网": "http://www.ahtba.org.cn/",
    "中国电建公共资源交易系统": "https://bid.powerchina.cn/",
    "隆道平台": "https://www.ebnew.com/",
}


def infer_cities(title: str) -> list[str]:
    # longer city names first to reduce substring mistakes; our cities are all 2 chars
    return [c for c in CITIES if c in title]


def fix_item(it: dict) -> dict:
    title = it.get("title") or ""
    title_cities = infer_cities(title)
    site_region = it.get("region") or it.get("province") or ""

    if title_cities:
        # prefer title project city; if multiple, keep those intersecting configured cities
        city = title_cities[0]
        # if current city is wrong/missing, override
        if it.get("city") not in title_cities:
            it["city"] = city
        else:
            city = it["city"]
        it["project_province"] = CITY_TO_PROVINCE.get(city, "")
    else:
        it["project_province"] = CITY_TO_PROVINCE.get(it.get("city") or "", it.get("province") or "")

    it["site_region"] = site_region  # 站点标注（发布侧，可能错）
    # display region = project province from title city
    it["region"] = it.get("project_province") or site_region

    src = it.get("source") or ""
    it["source_url"] = SOURCE_URLS.get(src, "")
    # detail: keep aggregation url, but mark
    uuid = it.get("uuid") or ""
    it["official_url"] = (
        f"https://ctbpsp.com/#/bulletinDetail?uuid={uuid}&inpvalue=&dataSource=0&tenderAgency="
    )
    it["detail_note"] = "聚合详情常需验证码；优先用来源平台"
    return it


HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>绿植招标结果（字段修正版）</title>
<style>
  :root { --bg:#f3f1eb; --panel:#fffdf8; --ink:#1c2430; --muted:#5d6b7a; --line:#d9d2c5; --accent:#0f6a4f; --accent-2:#c45c26; }
  *{box-sizing:border-box}
  body{margin:0;font-family:"Noto Sans SC","Segoe UI",sans-serif;color:var(--ink);background:radial-gradient(900px 400px at 10% -10%,#e7f2ec,transparent 55%),var(--bg)}
  .wrap{max-width:1220px;margin:0 auto;padding:28px 18px 48px}
  h1{margin:0 0 6px;font-size:26px}
  .sub{color:var(--muted);margin-bottom:14px;font-size:13px;line-height:1.5}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px;margin-bottom:14px}
  .filters{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}
  label{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted)}
  input,select,button{font:inherit;border:1px solid var(--line);border-radius:8px;padding:8px 10px;background:#fff}
  button{background:var(--accent);color:#fff;border-color:var(--accent);cursor:pointer}
  button.ghost{background:#fff;color:var(--ink)}
  .meta{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;color:var(--muted);font-size:13px;margin-top:8px}
  table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
  th,td{padding:10px 12px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top;font-size:13px}
  th{background:#f0ebe2;font-size:12px;color:var(--muted)}
  .title{font-weight:600;line-height:1.35}.muted{color:var(--muted)}
  a.link{color:var(--accent-2);text-decoration:none;font-weight:600;margin-right:8px}
  .tag{display:inline-block;padding:2px 7px;border-radius:999px;background:#e8f3ee;color:var(--accent);font-size:12px}
  .warn{color:var(--accent-2);font-size:12px}
  .pager{display:flex;gap:8px;align-items:center;justify-content:center;margin-top:14px}
  @media(max-width:960px){.filters{grid-template-columns:1fr 1fr}.hide-sm{display:none}}
</style>
</head>
<body>
<div class="wrap">
  <h1>绿植招标结果</h1>
  <div class="sub">
    「项目城市」来自标题；「站点地区」是平台标注（可能和项目地不一致，如电建系统标成浙江）。
    「看详情」走聚合站，常被验证码拦住；可先开「来源平台」，或复制标题到平台内搜。
  </div>
  <div class="panel">
    <div class="filters">
      <label>项目城市<select id="city"></select></label>
      <label>站点地区<select id="siteRegion"></select></label>
      <label>关键词<select id="keyword"></select></label>
      <label>投标状态
        <select id="bidStatus">
          <option value="">全部</option>
          <option value="open" selected>可投标/未开标</option>
          <option value="closed">已开标</option>
        </select>
      </label>
      <label>标题包含<input id="q" placeholder="搜索标题"></label>
      <label>每页<select id="pageSize"><option>10</option><option selected>20</option><option>50</option></select></label>
    </div>
    <div class="meta"><div id="stats"></div><button class="ghost" id="resetBtn" type="button">重置</button></div>
  </div>
  <table>
    <thead>
      <tr>
        <th style="width:36%">标题</th>
        <th>项目城市</th>
        <th class="hide-sm">站点地区</th>
        <th class="hide-sm">关键词</th>
        <th>发布</th>
        <th>开标</th>
        <th>状态</th>
        <th>链接</th>
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
const uniq = k => [...new Set(DATA.map(x => x[k]).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh'));
function fill(id, arr, label){document.getElementById(id).innerHTML = `<option value="">${label}</option>` + arr.map(v=>`<option value="${v}">${v}</option>`).join('');}
fill('city', uniq('city'), '全部城市');
fill('siteRegion', uniq('site_region'), '全部站点地区');
fill('keyword', uniq('keyword'), '全部关键词');
const citySel=document.getElementById('city'), siteSel=document.getElementById('siteRegion'), kwSel=document.getElementById('keyword');
const stSel=document.getElementById('bidStatus'), qInput=document.getElementById('q'), sizeSel=document.getElementById('pageSize');
const tbody=document.getElementById('tbody'), stats=document.getElementById('stats'), pageInfo=document.getElementById('pageInfo');
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function filtered(){
  const q=qInput.value.trim();
  return DATA.filter(r=>{
    if(citySel.value && r.city!==citySel.value) return false;
    if(siteSel.value && r.site_region!==siteSel.value) return false;
    if(kwSel.value && r.keyword!==kwSel.value) return false;
    if(stSel.value && r.bid_status_code!==stSel.value) return false;
    if(q && !(r.title||'').includes(q)) return false;
    return true;
  });
}
function render(){
  const rows=filtered(); const size=+sizeSel.value||20;
  const pages=Math.max(1, Math.ceil(rows.length/size)); if(page>pages) page=pages; if(page<1) page=1;
  const slice=rows.slice((page-1)*size, page*size);
  tbody.innerHTML = slice.map(r=>{
    const mismatch = r.site_region && r.project_province && r.site_region!==r.project_province;
    const srcLink = r.source_url ? `<a class="link" href="${esc(r.source_url)}" target="_blank" rel="noopener">来源平台</a>` : '';
    const detail = `<a class="link" href="${esc(r.official_url)}" target="_blank" rel="noopener" title="聚合站常需验证码">聚合详情</a>`;
    const copy = `<a class="link" href="#" data-copy="${esc(r.title)}">复制标题</a>`;
    return `<tr>
      <td><div class="title">${esc(r.title)}</div><div class="muted" style="margin-top:4px">${esc(r.source||'')}${mismatch?` <span class="warn">站点地区可能不准</span>`:''}</div></td>
      <td><span class="tag">${esc(r.city||'-')}</span></td>
      <td class="hide-sm">${esc(r.site_region||'-')}</td>
      <td class="hide-sm">${esc(r.keyword||'')}</td>
      <td>${esc(r.publish_date||'-')}</td>
      <td>${esc((r.open_time||'').slice(0,16)||'-')}</td>
      <td>${esc(r.bid_status||'-')}</td>
      <td>${srcLink}${detail}${copy}</td>
    </tr>`;
  }).join('') || `<tr><td colspan="8" class="muted">无结果</td></tr>`;
  stats.textContent = `共 ${rows.length} / ${DATA.length} · 第 ${page}/${pages} 页`;
  pageInfo.textContent = `${page}/${pages}`;
  document.getElementById('prev').disabled = page<=1;
  document.getElementById('next').disabled = page>=pages;
  tbody.querySelectorAll('[data-copy]').forEach(a=>a.addEventListener('click', e=>{
    e.preventDefault();
    navigator.clipboard.writeText(a.getAttribute('data-copy')||'');
    a.textContent='已复制';
    setTimeout(()=>a.textContent='复制标题', 1000);
  }));
}
[citySel,siteSel,kwSel,stSel,sizeSel].forEach(el=>el.addEventListener('change',()=>{page=1;render();}));
qInput.addEventListener('input',()=>{page=1;render();});
document.getElementById('prev').onclick=()=>{page--;render();};
document.getElementById('next').onclick=()=>{page++;render();};
document.getElementById('resetBtn').onclick=()=>{citySel.value='';siteSel.value='';kwSel.value='';stSel.value='open';qInput.value='';page=1;render();};
render();
</script>
</body>
</html>
"""


def main() -> None:
    items = json.loads(SRC.read_text(encoding="utf-8"))
    fixed = [fix_item(dict(x)) for x in items]
    # drop rows whose city not actually in title and not shanghai-special (optional keep)
    OUT_ITEMS.write_text(json.dumps(fixed, ensure_ascii=False, indent=2), encoding="utf-8")
    html = HTML.replace("__DATA__", json.dumps(fixed, ensure_ascii=False))
    OUT_HTML.write_text(html, encoding="utf-8")

    # verify 华曦府
    sample = [x for x in fixed if "华曦府" in x.get("title", "")]
    print(json.dumps({
        "count": len(fixed),
        "huaxi": sample[:1],
        "html": str(OUT_HTML),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
