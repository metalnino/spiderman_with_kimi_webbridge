"""Add bid_status to enriched items and rebuild viewer with open/closed filter."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "data" / "trial" / "items_enriched.json"
VIEWER = ROOT / "data" / "trial" / "viewer.html"
NOW = datetime.now()


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


def status_of(item: dict) -> dict:
    ot = parse_dt(item.get("open_time"))
    if not ot:
        return {"bid_status": "未知", "bid_status_code": "unknown", "days_to_open": None}
    delta = (ot - NOW).total_seconds()
    if delta > 0:
        days = max(0, int(delta // 86400))
        return {"bid_status": "可投标/未开标", "bid_status_code": "open", "days_to_open": days}
    return {"bid_status": "已开标", "bid_status_code": "closed", "days_to_open": 0}


def main() -> None:
    items = json.loads(ITEMS.read_text(encoding="utf-8"))
    for it in items:
        it.update(status_of(it))
    ITEMS.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    html = VIEWER.read_text(encoding="utf-8")
    # replace embedded DATA
    html = re.sub(
        r"const DATA = \[.*?\];\nlet page = 1;",
        "const DATA = " + json.dumps(items, ensure_ascii=False) + ";\nlet page = 1;",
        html,
        count=1,
        flags=re.S,
    )

    # add status filter if missing
    if 'id="bidStatus"' not in html:
        html = html.replace(
            """<label>标题包含
          <input id="q" placeholder="搜索标题" />
        </label>""",
            """<label>投标状态
          <select id="bidStatus">
            <option value="">全部状态</option>
            <option value="open" selected>可投标/未开标</option>
            <option value="closed">已开标</option>
            <option value="unknown">未知</option>
          </select>
        </label>
        <label>标题包含
          <input id="q" placeholder="搜索标题" />
        </label>""",
        )
        html = html.replace(
            "grid-template-columns: repeat(6, minmax(0, 1fr));",
            "grid-template-columns: repeat(7, minmax(0, 1fr));",
        )
        # filter logic
        html = html.replace(
            "const q = qInput.value.trim();\n  let rows = DATA.filter(r => {\n    if (city && r.city !== city) return false;\n    if (keyword && r.keyword !== keyword) return false;\n    if (province && r.province !== province) return false;\n    if (q && !(r.title || '').includes(q)) return false;\n    return true;\n  });",
            "const q = qInput.value.trim();\n  const bidStatus = bidStatusSel.value;\n  let rows = DATA.filter(r => {\n    if (city && r.city !== city) return false;\n    if (keyword && r.keyword !== keyword) return false;\n    if (province && r.province !== province) return false;\n    if (bidStatus && r.bid_status_code !== bidStatus) return false;\n    if (q && !(r.title || '').includes(q)) return false;\n    return true;\n  });",
        )
        html = html.replace(
            "const qInput = document.getElementById('q');",
            "const qInput = document.getElementById('q');\nconst bidStatusSel = document.getElementById('bidStatus');",
        )
        html = html.replace(
            "[citySel,keywordSel,provinceSel,sortSel,pageSizeSel]",
            "[citySel,keywordSel,provinceSel,bidStatusSel,sortSel,pageSizeSel]",
        )
        html = html.replace(
            "citySel.value=''; keywordSel.value=''; provinceSel.value=''; qInput.value='';",
            "citySel.value=''; keywordSel.value=''; provinceSel.value=''; bidStatusSel.value='open'; qInput.value='';",
        )
        # show status column near open time
        html = html.replace(
            "<th>开标</th>\n          <th>金额</th>",
            "<th>开标</th>\n          <th>状态</th>\n          <th>金额</th>",
        )
        html = html.replace(
            "<td>${escapeHtml((r.open_time||'').slice(0,16)||'-')}</td>\n      <td>${r.amount == null",
            "<td>${escapeHtml((r.open_time||'').slice(0,16)||'-')}</td>\n      <td>${escapeHtml(r.bid_status||'-')}${r.bid_status_code==='open' && r.days_to_open!=null ? ` <span class=\"muted\">(${r.days_to_open}天)</span>` : ''}</td>\n      <td>${r.amount == null",
        )
        html = html.replace(
            '`</tr>\n  `).join(\'\') || `<tr><td colspan="8"',
            '`</tr>\n  `).join(\'\') || `<tr><td colspan="9"',
        )
        html = html.replace(
            '来源：中国招标投标公共服务平台 · 金额字段列表页无，排序时空值靠后 · 官网链到详情页',
            '来源：中国招标投标公共服务平台 · 默认可投标=开标时间未到 · 金额见官网 · 词表已扩到 config/crawl_config.json',
        )

    VIEWER.write_text(html, encoding="utf-8")
    open_n = sum(1 for x in items if x.get("bid_status_code") == "open")
    print(json.dumps({"total": len(items), "open": open_n, "closed": len(items) - open_n, "viewer": str(VIEWER)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
