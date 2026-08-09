"""Generate simplest incremental notices list HTML from MySQL."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect  # noqa: E402

OUT_PATH = ROOT / "data" / "web" / "incremental.html"
LIMIT = 200
NEW_HOURS = 48

SQL = """
SELECT
  title,
  source_name,
  source_id,
  city,
  keyword,
  publish_date,
  created_at,
  detail_url,
  official_url
FROM notices
ORDER BY created_at DESC
LIMIT %s
"""


def _fmt_dt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _is_new(created_at, now: datetime) -> bool:
    if created_at is None:
        return False
    if not isinstance(created_at, datetime):
        return False
    return created_at >= now - timedelta(hours=NEW_HOURS)


def _detail_href(row: dict) -> str:
    url = (row.get("detail_url") or row.get("official_url") or "").strip()
    return url


def fetch_recent_notices(limit: int = LIMIT) -> list[dict]:
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(SQL, (limit,))
            return list(cur.fetchall())
    finally:
        conn.close()


def render_html(rows: list[dict], *, now: datetime | None = None) -> str:
    now = now or datetime.now()
    generated = now.strftime("%Y-%m-%d %H:%M:%S")
    body_rows: list[str] = []

    if not rows:
        body_rows.append(
            '<tr><td colspan="8" class="empty">暂无公告数据</td></tr>'
        )
    else:
        for row in rows:
            title = escape(str(row.get("title") or "-"))
            source = escape(str(row.get("source_name") or row.get("source_id") or "-"))
            city = escape(str(row.get("city") or "-"))
            keyword = escape(str(row.get("keyword") or "-"))
            publish = escape(_fmt_dt(row.get("publish_date")))
            created = escape(_fmt_dt(row.get("created_at")))
            new_flag = "是" if _is_new(row.get("created_at"), now) else "否"
            href = _detail_href(row)
            if href:
                link = f'<a href="{escape(href, quote=True)}" target="_blank" rel="noopener">查看</a>'
            else:
                link = "-"
            new_cls = ' class="new"' if new_flag == "是" else ""
            body_rows.append(
                "<tr>"
                f"<td>{title}</td>"
                f"<td>{source}</td>"
                f"<td>{city}</td>"
                f"<td>{keyword}</td>"
                f"<td>{publish}</td>"
                f"<td>{created}</td>"
                f"<td{new_cls}>{new_flag}</td>"
                f"<td>{link}</td>"
                "</tr>"
            )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>增量公告列表</title>
<style>
  :root {{
    --bg: #f7f8fa;
    --card: #ffffff;
    --text: #1f2329;
    --muted: #646a73;
    --border: #e5e6eb;
    --new: #0d7a3f;
    --link: #0b5fff;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.5;
  }}
  main {{
    max-width: 1200px;
    margin: 0 auto;
    padding: 28px 20px 48px;
  }}
  h1 {{
    margin: 0 0 8px;
    font-size: 22px;
    font-weight: 650;
  }}
  .meta {{
    margin: 0 0 20px;
    color: var(--muted);
    font-size: 13px;
  }}
  .wrap {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: auto;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  th, td {{
    padding: 10px 12px;
    border-bottom: 1px solid var(--border);
    text-align: left;
    vertical-align: top;
  }}
  th {{
    background: #f2f3f5;
    font-weight: 600;
    white-space: nowrap;
  }}
  tr:last-child td {{ border-bottom: none; }}
  td.new {{ color: var(--new); font-weight: 650; }}
  td.empty {{
    text-align: center;
    color: var(--muted);
    padding: 48px 12px;
  }}
  a {{ color: var(--link); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<main>
  <h1>增量公告列表</h1>
  <p class="meta">按首次发现时间倒序，最多 {LIMIT} 条；NEW = 首次发现于 {NEW_HOURS} 小时内。生成时间：{escape(generated)}；当前 {len(rows)} 条。</p>
  <div class="wrap">
    <table>
      <thead>
        <tr>
          <th>标题</th>
          <th>源站</th>
          <th>城市</th>
          <th>关键词</th>
          <th>发布时间</th>
          <th>首次发现时间</th>
          <th>是否 NEW</th>
          <th>详情</th>
        </tr>
      </thead>
      <tbody>
        {"".join(body_rows)}
      </tbody>
    </table>
  </div>
</main>
</body>
</html>
"""


def build_incremental_list(
    out_path: Path | None = None,
    *,
    limit: int = LIMIT,
) -> Path:
    path = Path(out_path) if out_path else OUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = fetch_recent_notices(limit=limit)
    html = render_html(rows)
    path.write_text(html, encoding="utf-8")
    return path


if __name__ == "__main__":
    out = build_incremental_list()
    print(f"WROTE {out}")
