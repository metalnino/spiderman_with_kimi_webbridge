"""任务完成后的「增量简报」邮件：把本轮新增公告渲染成 HTML 发到 QQ 邮箱。

口径（一句话）：简报 = 本轮新增（去重后）明细 + 城市/关键词分布 + 平台健康度。
发信走 scripts.email_gateway（Gmail SMTP → EMAIL_TO，默认 279152260@qq.com）。
SPIDER_NO_EMAIL=1 整体关闭（本地调试/测试用）；发送失败绝不向上抛（采集主流程不受影响）。

纯渲染函数 render_html / build_subject / build_summary_from_report 无副作用，可单测；
send_briefing / send_from_collector / send_from_http 是发送封装，统一 try/except 兜底。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import email_gateway as eg  # noqa: E402

# 邮件里最多列多少条新增明细；超出折叠为「其余 N 条略，详见运营台」。
MAX_ITEMS = 80

TITLE = "绿植招采简报"

# 邮件色板（inline style，兼容 QQ 邮箱的弱 CSS 渲染）
COLOR = {
    "bg": "#f4f6f8",
    "card": "#ffffff",
    "text": "#1f2329",
    "muted": "#7a8087",
    "line": "#e6e8eb",
    "brand": "#0d7a3f",
    "brand_dark": "#0a5c2f",
    "accent": "#0b5fff",
    "warn": "#b54708",
    "bad": "#c0392b",
}


def _fmt(v) -> str:
    if v is None or str(v).strip() == "":
        return "-"
    return escape(str(v))


def _fmt_dt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    return escape(str(v)[:16])


def _time_label(summary: dict) -> str:
    """简报时间标签：优先 started_at，其次 finished_at，最后当前时间。"""
    raw = summary.get("started_at") or summary.get("finished_at") or ""
    s = str(raw).strip()
    if s:
        return escape(s.replace("T", " ")[:16])
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _esc_url(url: str) -> str:
    return escape((url or "").strip(), quote=True)


def _counts(items: list[dict]) -> tuple[dict, dict]:
    """城市分布 + 关键词分布（按条数降序）。"""
    city: dict[str, int] = {}
    kw: dict[str, int] = {}
    for it in items:
        c = (it.get("city") or "").strip() or "未知"
        k = (it.get("keyword") or "").strip() or "未标词"
        city[c] = city.get(c, 0) + 1
        kw[k] = kw.get(k, 0) + 1
    return (
        dict(sorted(city.items(), key=lambda x: (-x[1], x[0]))),
        dict(sorted(kw.items(), key=lambda x: (-x[1], x[0]))),
    )


def _stat_cards(summary: dict, items: list[dict], city: dict) -> str:
    """顶部指标卡：新增 / 抓取 / 平台成功 / 覆盖城市 / 封禁。"""
    new = summary.get("new", len(items))
    fetched = summary.get("fetched", 0)
    total_p = summary.get("platforms_total") or 0
    ok_p = summary.get("platforms_ok") or 0
    blocked = summary.get("blocked") or 0
    pct = f"{ok_p}/{total_p}" if total_p else "-"

    def card(label: str, value: str, color: str) -> str:
        return (
            f'<td align="center" style="padding:12px 8px;background:{COLOR["card"]};'
            f'border:1px solid {COLOR["line"]};border-radius:6px;">'
            f'<div style="font-size:20px;font-weight:700;color:{color};">{value}</div>'
            f'<div style="font-size:12px;color:{COLOR["muted"]};margin-top:4px;">{label}</div></td>'
        )

    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:separate;border-spacing:6px;margin:0 -6px;"><tr>'
        + card("本轮新增", str(new), COLOR["brand"])
        + card("抓取原始", str(fetched), COLOR["text"])
        + card("平台成功", pct, COLOR["accent"])
        + card("覆盖城市", str(len(city)), COLOR["text"])
        + card("封禁事件", str(blocked), COLOR["bad"] if blocked else COLOR["muted"])
        + "</tr></table>"
    )


def _dist_table(title: str, counts: dict) -> str:
    """两列表：名称 | 条数。用于城市分布 / 关键词分布。"""
    if not counts:
        return ""
    rows = "".join(
        f'<tr><td style="padding:6px 10px;border-bottom:1px solid {COLOR["line"]};'
        f'color:{COLOR["text"]};">{escape(k)}</td>'
        f'<td align="right" style="padding:6px 10px;border-bottom:1px solid {COLOR["line"]};'
        f'color:{COLOR["brand"]};font-weight:600;">{v}</td></tr>'
        for k, v in counts.items()
    )
    return (
        f'<div style="margin:14px 0 4px;font-size:14px;font-weight:600;color:{COLOR["text"]};">{escape(title)}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;background:{COLOR["card"]};'
        f'border:1px solid {COLOR["line"]};border-radius:6px;overflow:hidden;font-size:13px;">'
        f"<tbody>{rows}</tbody></table>"
    )


def _items_table(items: list[dict]) -> str:
    """新增明细表：标题(链接) | 城市 | 关键词 | 源站 | 发布时间。"""
    rows = []
    for it in items:
        title = escape(str(it.get("title") or "-"))
        url = _esc_url(str(it.get("url") or ""))
        title_cell = f'<a href="{url}" style="color:{COLOR["accent"]};text-decoration:none;" target="_blank">{title}</a>' if url else title
        rows.append(
            "<tr>"
            f'<td style="padding:8px 10px;border-bottom:1px solid {COLOR["line"]};font-size:13px;">{title_cell}</td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid {COLOR["line"]};font-size:12px;color:{COLOR["text"]};white-space:nowrap;">{_fmt(it.get("city"))}</td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid {COLOR["line"]};font-size:12px;color:{COLOR["muted"]};white-space:nowrap;">{_fmt(it.get("keyword"))}</td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid {COLOR["line"]};font-size:12px;color:{COLOR["text"]};white-space:nowrap;">{_fmt(it.get("platform"))}</td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid {COLOR["line"]};font-size:12px;color:{COLOR["muted"]};white-space:nowrap;">{_fmt_dt(it.get("publish_date"))}</td>'
            "</tr>"
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="border-collapse:collapse;background:{COLOR["card"]};'
        f'border:1px solid {COLOR["line"]};border-radius:6px;overflow:hidden;font-size:12px;">'
        "<thead><tr>"
        f'<th align="left" style="padding:8px 10px;background:#f0f2f4;color:{COLOR["text"]};font-size:12px;">标题</th>'
        f'<th align="left" style="padding:8px 10px;background:#f0f2f4;color:{COLOR["text"]};font-size:12px;">城市</th>'
        f'<th align="left" style="padding:8px 10px;background:#f0f2f4;color:{COLOR["text"]};font-size:12px;">关键词</th>'
        f'<th align="left" style="padding:8px 10px;background:#f0f2f4;color:{COLOR["text"]};font-size:12px;">源站</th>'
        f'<th align="left" style="padding:8px 10px;background:#f0f2f4;color:{COLOR["text"]};font-size:12px;">发布时间</th>'
        "</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _alert(problems: list[str]) -> str:
    """失败/空平台等问题的警示块。"""
    if not problems:
        return ""
    items = "".join(
        f'<li style="margin:2px 0;">{escape(p)}</li>' for p in problems[:10]
    )
    return (
        f'<div style="margin:14px 0 4px;padding:10px 12px;background:#fdf3e7;'
        f'border:1px solid #f5cba7;border-radius:6px;font-size:13px;color:{COLOR["warn"]};">'
        f'<div style="font-weight:600;margin-bottom:4px;">⚠ 需关注</div>'
        f'<ul style="margin:0;padding-left:18px;">{items}</ul></div>'
    )


def render_html(summary: dict, items: list[dict], *, now: datetime | None = None) -> str:
    """渲染简报 HTML（email-safe：全 inline style + table 布局）。"""
    now = now or datetime.now()
    items = list(items or [])
    city, kw = _counts(items)
    new = summary.get("new", len(items))
    problems: list[str] = []
    for pid in summary.get("failed_platforms") or []:
        problems.append(f"平台 {pid} 本轮失败/出错")
    for pid in summary.get("empty_platforms") or []:
        problems.append(f"平台 {pid} 本轮 0 条结果")

    shown = items[:MAX_ITEMS]
    overflow = len(items) - len(shown)

    # 无新增：正文放一句明确结论，避免空表
    if new <= 0 and not items:
        body = (
            f'<div style="padding:16px;text-align:center;color:{COLOR["muted"]};'
            f'background:{COLOR["card"]};border:1px solid {COLOR["line"]};border-radius:6px;font-size:14px;">'
            "本轮无新增公告"
            "</div>"
        )
    else:
        body = _items_table(shown)
        if overflow > 0:
            body += (
                f'<div style="margin-top:8px;font-size:12px;color:{COLOR["muted"]};">'
                f"…其余 {overflow} 条略，详见运营台增量列表</div>"
            )

    dist = _dist_table("城市分布", city) + _dist_table("关键词分布", kw)

    extra_notes = "".join(
        f'<div style="margin:6px 0;font-size:12px;color:{COLOR["muted"]};">· {escape(str(n))}</div>'
        for n in (summary.get("notes") or [])
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{escape(TITLE)}</title>
</head>
<body style="margin:0;padding:0;background:{COLOR['bg']};font-family:'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;color:{COLOR['text']};">
<div style="max-width:680px;margin:0 auto;padding:16px 12px 32px;">
  <div style="background:{COLOR['brand']};border-radius:8px 8px 0 0;padding:16px 20px;color:#fff;">
    <div style="font-size:18px;font-weight:700;">{escape(TITLE)}</div>
    <div style="font-size:12px;margin-top:4px;opacity:.9;">任务时间 {_time_label(summary)} · 运行号 {_fmt(summary.get('run_id'))}</div>
  </div>
  <div style="background:{COLOR['card']};border:1px solid {COLOR['line']};border-top:none;border-radius:0 0 8px 8px;padding:16px 20px;">
    {_stat_cards(summary, items, city)}
    {_alert(problems)}
    {dist}
    <div style="margin:14px 0 4px;font-size:14px;font-weight:600;">新增明细（{new} 条）</div>
    {body}
    {extra_notes}
    <div style="margin-top:16px;padding-top:10px;border-top:1px solid {COLOR['line']};font-size:11px;color:{COLOR['muted']};">
      本邮件由采集任务自动生成 · {escape(now.strftime('%Y-%m-%d %H:%M:%S'))}
    </div>
  </div>
</div>
</body>
</html>
"""


def _plain_fallback(summary: dict, items: list[dict]) -> str:
    """不支持 HTML 的客户端看纯文本回退。"""
    new = summary.get("new", len(items))
    lines = [
        f"{TITLE} · {_time_label(summary)}",
        f"本轮新增 {new} 条 / 抓取 {summary.get('fetched', 0)} 条",
    ]
    for it in items[:MAX_ITEMS]:
        lines.append(f"- [{it.get('city') or '-'}][{it.get('keyword') or '-'}] {it.get('title') or '-'}")
    return "\n".join(lines)


def build_subject(summary: dict, items: list[dict] | None = None) -> str:
    """主题：日期时间 + 新增数 + 头部城市（纯文本，不做 HTML 转义）。"""
    raw = summary.get("started_at") or summary.get("finished_at") or ""
    label = str(raw).strip().replace("T", " ")[:16] or datetime.now().strftime("%Y-%m-%d %H:%M")
    new = summary.get("new", len(items or []))
    city, _ = _counts(items or [])
    top = " · ".join(f"{c} {n}" for c, n in list(city.items())[:3])
    parts = [f"【{TITLE}】{label} 新增 {new} 条"]
    if top:
        parts.append(top)
    return "｜".join(parts)


def build_summary_from_report(report: dict, items: list[dict]) -> dict:
    """从采集员观测报告 + 新增明细提炼简报 summary（渲染/主题用）。"""
    m = report.get("metrics") or {}
    pp = report.get("perPlatform") or []
    return {
        "run_id": report.get("runId") or "",
        "started_at": report.get("startedAt") or "",
        "finished_at": report.get("finishedAt") or "",
        "fetched": int(m.get("fetched_count") or 0),
        "new": len(items),
        "platforms_total": len(pp),
        "platforms_ok": sum(1 for p in pp if p.get("status") in ("success", "partial")),
        "failed_platforms": [p.get("platform") for p in pp if p.get("status") in ("failed", "error")],
        "empty_platforms": list(m.get("empty_platforms") or []),
        "blocked": int(m.get("blocked_count") or 0),
        "elapsed_ms": int(m.get("elapsed_ms") or 0),
        # 简报只保留可操作的提醒（任务书到期等），不堆砌指标口径长文
        "notes": [n for n in (report.get("notes") or []) if str(n).startswith("任务书")],
    }


def _normalize_items(raw_items: list[dict]) -> list[dict]:
    """内核通知 dict → 简报条目（title/platform/city/keyword/publish_date/url）。"""
    out = []
    for n in raw_items or []:
        out.append({
            "title": n.get("title") or "",
            "platform": n.get("source_name") or n.get("source_id") or "",
            "city": n.get("city") or "",
            "keyword": n.get("keyword") or "",
            "publish_date": n.get("publish_date") or "",
            "url": (n.get("detail_url") or n.get("official_url") or "").strip(),
        })
    return out


def send_briefing(summary: dict, items: list[dict], *, to: str | None = None, subject: str | None = None) -> dict:
    """渲染并发送简报邮件。返回 email_gateway 结果 dict；任何异常兜底不抛。"""
    if os.environ.get("SPIDER_NO_EMAIL"):
        return {"ok": False, "error": "disabled_by_SPIDER_NO_EMAIL", "skipped": True}
    try:
        html = render_html(summary, items)
        subj = subject or build_subject(summary, items)
        to = to or eg.default_to()
        return eg.send_html(to, subj, html, body_text=_plain_fallback(summary, items))
    except Exception as e:  # noqa: BLE001 —— 发信失败绝不炸采集主流程
        return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def send_from_collector(report: dict, new_notices: list[dict], *, to: str | None = None) -> dict:
    """采集员任务完成钩子：由观测报告 + 本轮新增原始通知发简报。"""
    items = _normalize_items(new_notices)
    summary = build_summary_from_report(report, items)
    return send_briefing(summary, items, to=to)


_BLOCK_MARKERS = ("http 403", "rate_limited", "频繁", "频控", "封禁", "blocked")


def build_summary_from_http(results: list[dict], items: list[dict]) -> dict:
    """HTTP 增量入口（run_incremental.py）的简报 summary。"""
    fetched = sum(int(r.get("raw_total") or len(r.get("notices") or [])) for r in results)
    ok = sum(1 for r in results if r.get("status") in ("success", "partial"))
    failed = [r.get("source_id") for r in results if r.get("status") in ("failed", "error")]
    empty = [
        r.get("source_id")
        for r in results
        if (int(r.get("raw_total") or 0) == 0) and r.get("status") not in ("skipped", "failed", "error")
    ]
    blocked = sum(
        1
        for r in results
        if any(m in str(r.get("error") or "").lower() for m in _BLOCK_MARKERS)
    )
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "run_id": now.replace(":", "").replace("-", "").replace("T", "-"),
        "started_at": now,
        "finished_at": now,
        "fetched": fetched,
        "new": len(items),
        "platforms_total": len(results),
        "platforms_ok": ok,
        "failed_platforms": failed,
        "empty_platforms": empty,
        "blocked": blocked,
        "elapsed_ms": 0,
        "notes": [],
    }


def send_from_http(results: list[dict], watermark, *, to: str | None = None) -> dict:
    """HTTP 增量入口完成钩子：按 created_at 水位取新增并发简报。watermark=None 时不取（DB 不可达）。"""
    items = fetch_new_notices_since(watermark) if watermark is not None else []
    summary = build_summary_from_http(results, items)
    return send_briefing(summary, items, to=to)


def last_watermark():
    """DB 端已收录公告的最新 created_at（服务器时钟，跨机一致，无时钟漂移）。"""
    from scripts.db import connect

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT MAX(created_at) AS t FROM notices")
            row = cur.fetchone()
            return row["t"] if row and row.get("t") else None
    finally:
        conn.close()


def fetch_new_notices_since(watermark, *, limit: int = 200) -> list[dict]:
    """按 created_at 水位取增量公告（HTTP 入口用；watermark 为上一轮 MAX(created_at)）。"""
    from scripts.db import connect

    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT title, source_id, source_name, city, keyword, publish_date, detail_url, official_url "
                "FROM notices WHERE created_at > %s ORDER BY created_at DESC LIMIT %s",
                (watermark, limit),
            )
            rows = list(cur.fetchall())
    finally:
        conn.close()
    return [
        {
            "title": r.get("title") or "",
            "platform": r.get("source_name") or r.get("source_id") or "",
            "city": r.get("city") or "",
            "keyword": r.get("keyword") or "",
            "publish_date": _fmt_dt(r.get("publish_date")),
            "url": (r.get("detail_url") or r.get("official_url") or "").strip(),
        }
        for r in rows
    ]
