"""Build ops dashboard HTML: monitor / incremental / clean / workbench."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect  # noqa: E402

from crawl.filters import PROVINCE_CITY, source_capability_hint

OUT = ROOT / "data" / "web" / "dashboard.html"


def _rows(sql: str, args=()):
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            return list(cur.fetchall())
    finally:
        conn.close()


def build_dashboard() -> Path:
    notices = _rows(
        "SELECT id, title, source_id, source_name, city, province, keyword, publish_date, created_at, "
        "detail_url, clean_status, clean_reason, manual_label, amount_text "
        "FROM notices ORDER BY created_at DESC LIMIT 300"
    )
    runs = _rows(
        "SELECT id, source_id, status, item_count, note, started_at, finished_at "
        "FROM crawl_runs ORDER BY id DESC LIMIT 40"
    )
    clean_stats = _rows(
        "SELECT decision, COUNT(*) AS c FROM clean_events "
        "WHERE created_at >= (NOW() - INTERVAL 7 DAY) GROUP BY decision"
    )
    drop_reasons = _rows(
        "SELECT reason, COUNT(*) AS c FROM clean_events WHERE decision='drop' "
        "GROUP BY reason ORDER BY c DESC LIMIT 15"
    )
    keywords = _rows("SELECT keyword, enabled, group_name FROM keyword_state ORDER BY enabled DESC, keyword")
    todos = _rows(
        "SELECT id, source_id, title, status, note, created_at FROM captcha_todos "
        "ORDER BY FIELD(status,'open','closed'), id DESC LIMIT 40"
    )

    def fmt(v):
        if v is None:
            return "-"
        if isinstance(v, datetime):
            return v.strftime("%Y-%m-%d %H:%M")
        return str(v)

    now = datetime.now()
    notice_trs = []
    for r in notices:
        is_new = False
        if isinstance(r.get("created_at"), datetime):
            is_new = r["created_at"] >= now - timedelta(hours=48)
        hint = source_capability_hint(r.get("source_id") or "") or ""
        hint_html = ""
        if r.get("source_id") == "chinabidding" and hint:
            hint_html = "<br><small>" + escape(hint) + "</small>"
        link_html = "-"
        if r.get("detail_url"):
            link_html = '<a href="' + escape(r["detail_url"]) + '" target="_blank">链接</a>'
        notice_trs.append(
            "<tr>"
            f"<td>{'NEW' if is_new else ''}</td>"
            f"<td>{escape(r.get('source_id') or '')}</td>"
            f"<td>{escape(r.get('city') or '-')}</td>"
            f"<td>{escape(r.get('keyword') or '-')}</td>"
            f"<td>{escape(r.get('clean_status') or '-')}<br><small>{escape(r.get('clean_reason') or '')}</small></td>"
            f"<td>{escape(r.get('manual_label') or '-')}</td>"
            f"<td>{escape((r.get('title') or '')[:120])}{hint_html}</td>"
            f"<td>{escape(fmt(r.get('created_at')))}</td>"
            f"<td>{link_html}</td>"
            "</tr>"
        )

    run_trs = "".join(
        "<tr>"
        f"<td>{r['id']}</td><td>{escape(r['source_id'])}</td><td>{escape(r['status'])}</td>"
        f"<td>{r['item_count']}</td><td>{escape(fmt(r.get('started_at')))}</td>"
        f"<td>{escape((r.get('note') or '')[:100])}</td></tr>"
        for r in runs
    )
    kw_trs = "".join(
        f"<tr><td>{escape(k['keyword'])}</td><td>{'启用' if k['enabled'] else '停用'}</td>"
        f"<td>{escape(k.get('group_name') or '-')}</td></tr>"
        for k in keywords
    )
    todo_trs = "".join(
        f"<tr><td>{t['id']}</td><td>{escape(t['source_id'])}</td><td>{escape(t['status'])}</td>"
        f"<td>{escape((t.get('title') or '')[:80])}</td><td>{escape((t.get('note') or '')[:80])}</td></tr>"
        for t in todos
    )
    clean_sum = "".join(f"<li>{escape(x['decision'])}: {x['c']}</li>" for x in clean_stats) or "<li>暂无</li>"
    drop_sum = "".join(f"<li>{escape(x['reason'] or '-')}: {x['c']}</li>" for x in drop_reasons) or "<li>暂无</li>"
    prov_opts = "".join(f"<option value='{escape(p)}'>{escape(p)}</option>" for p in PROVINCE_CITY)
    city_map_json = json.dumps(PROVINCE_CITY, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/>
<title>招采运营台</title>
<style>
body{{font-family:Microsoft YaHei,Segoe UI,sans-serif;margin:0;background:#f5f6f8;color:#1f2329}}
header{{background:#111827;color:#fff;padding:16px 24px}}
nav{{display:flex;gap:8px;padding:12px 24px;background:#fff;border-bottom:1px solid #e5e7eb}}
nav button{{border:1px solid #d1d5db;background:#fff;padding:8px 12px;cursor:pointer}}
nav button.active{{background:#111827;color:#fff;border-color:#111827}}
section{{display:none;padding:20px 24px}}
section.active{{display:block}}
table{{border-collapse:collapse;width:100%;background:#fff}}
th,td{{border:1px solid #e5e7eb;padding:8px;font-size:13px;vertical-align:top}}
th{{background:#f3f4f6;text-align:left}}
.filters{{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}}
.hint{{color:#6b7280;font-size:12px}}
.cards{{display:flex;gap:12px;flex-wrap:wrap}}
.card{{background:#fff;border:1px solid #e5e7eb;padding:12px 16px;min-width:160px}}
</style></head><body>
<header><h1>绿植招采运营台</h1><div class="hint">生成时间 {escape(now.strftime('%Y-%m-%d %H:%M:%S'))} · 公告 {len(notices)} 条</div></header>
<nav>
  <button class="active" data-tab="monitor">运行监控</button>
  <button data-tab="incr">信息获取</button>
  <button data-tab="clean">清洗质量</button>
  <button data-tab="work">线索工作台</button>
  <button data-tab="kw">词库</button>
  <button data-tab="captcha">验证码待办</button>
</nav>

<section id="monitor" class="active">
  <h2>运行监控</h2>
  <table><thead><tr><th>ID</th><th>源站</th><th>状态</th><th>条数</th><th>开始</th><th>备注</th></tr></thead>
  <tbody>{run_trs or '<tr><td colspan=6>暂无任务</td></tr>'}</tbody></table>
</section>

<section id="incr">
  <h2>信息获取（增量）</h2>
  <p class="hint">NEW = 首次发现 48 小时内</p>
  <table><thead><tr><th>NEW</th><th>源站</th><th>城市</th><th>词</th><th>清洗</th><th>人工</th><th>标题</th><th>发现时间</th><th>链接</th></tr></thead>
  <tbody id="noticeBody">{''.join(notice_trs) or '<tr><td colspan=9>暂无数据</td></tr>'}</tbody></table>
</section>

<section id="clean">
  <h2>清洗质量</h2>
  <div class="cards"><div class="card"><b>近7日决策</b><ul>{clean_sum}</ul></div>
  <div class="card"><b>丢弃原因 Top</b><ul>{drop_sum}</ul></div></div>
</section>

<section id="work">
  <h2>线索工作台（级联筛选）</h2>
  <div class="filters">
    <label>源站 <select id="fSource"><option value="">全部</option>
      <option value="cebpub">cebpub</option><option value="chinabidding">chinabidding</option>
      <option value="ggzy">ggzy</option><option value="ccgp">ccgp</option>
      <option value="jsggzy">jsggzy</option><option value="jiangsu_zhaobiao">jiangsu_zhaobiao</option></select></label>
    <label>省 <select id="fProv"><option value="">全部</option>{prov_opts}</select></label>
    <label>市 <select id="fCity"><option value="">全部</option></select></label>
    <label>仅通过 <input type="checkbox" id="fPass"/></label>
  </div>
  <p class="hint" id="capHint"></p>
  <table><thead><tr><th>源站</th><th>城市</th><th>清洗</th><th>标题</th></tr></thead>
  <tbody id="workBody"></tbody></table>
</section>

<section id="kw">
  <h2>词库</h2>
  <table><thead><tr><th>关键词</th><th>状态</th><th>分组</th></tr></thead><tbody>{kw_trs or '<tr><td colspan=3>请先 seed</td></tr>'}</tbody></table>
</section>

<section id="captcha">
  <h2>验证码待办</h2>
  <table><thead><tr><th>ID</th><th>源站</th><th>状态</th><th>标题</th><th>备注</th></tr></thead>
  <tbody>{todo_trs or '<tr><td colspan=5>暂无</td></tr>'}</tbody></table>
</section>

<script>
const CITY_MAP = {city_map_json};
const ALL = {json.dumps([
  {
    "source_id": r.get("source_id"),
    "city": r.get("city"),
    "province": r.get("province"),
    "clean_status": r.get("clean_status"),
    "title": r.get("title"),
    "manual_label": r.get("manual_label"),
  }
  for r in notices
], ensure_ascii=False)};
document.querySelectorAll('nav button').forEach(btn=>{{
  btn.onclick=()=>{{
    document.querySelectorAll('nav button').forEach(b=>b.classList.remove('active'));
    document.querySelectorAll('section').forEach(s=>s.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  }};
}});
const fProv=document.getElementById('fProv');
const fCity=document.getElementById('fCity');
const fSource=document.getElementById('fSource');
const fPass=document.getElementById('fPass');
function refillCities(){{
  const p=fProv.value; const keep=fCity.value; fCity.innerHTML='<option value=\"\">全部</option>';
  (CITY_MAP[p]||[]).forEach(c=>{{const o=document.createElement('option');o.value=c;o.textContent=c;fCity.appendChild(o);}});
  // 级联：省变更清空市（若原市不在新省下）
  if(!(CITY_MAP[p]||[]).includes(keep)) fCity.value=''; else fCity.value=keep;
}}
function renderWork(){{
  const sid=fSource.value, p=fProv.value, c=fCity.value, only=fPass.checked;
  const hint=document.getElementById('capHint');
  hint.textContent = sid==='chinabidding' ? '采招网：无金额/详情需登录' : '';
  const rows=ALL.filter(r=>{{
    if(sid && r.source_id!==sid) return false;
    if(c && r.city!==c) return false;
    if(p){{
      const cities=CITY_MAP[p]||[];
      if(r.city && !cities.includes(r.city) && r.province!==p) return false;
    }}
    if(only && r.clean_status==='drop') return false;
    if(r.manual_label==='irrelevant') return false;
    return true;
  }});
  document.getElementById('workBody').innerHTML = rows.slice(0,100).map(r=>`<tr><td>${{r.source_id||''}}</td><td>${{r.city||'-'}}</td><td>${{r.clean_status||'-'}}</td><td>${{(r.title||'').slice(0,100)}}</td></tr>`).join('') || '<tr><td colspan=4>无匹配</td></tr>';
}}
fProv.onchange=()=>{{refillCities(); renderWork();}};
fCity.onchange=renderWork; fSource.onchange=renderWork; fPass.onchange=renderWork;
refillCities(); renderWork();
</script>
</body></html>"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    return OUT
