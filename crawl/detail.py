"""详情字段抓取与回填。HTTP 优先（ccgp 详情开放已验证）；其余站待接入。

各站详情现状（2026-08 探针）：
- ccgp：详情开放，HTTP 直取可拿 金额/招标人/代理/项目编号/联系方式
- ggzy：详情正文 JS 动态加载，静态 HTML 只有标题+项目编号（需详情 API 或 WebBridge）
- jiangsu_zhaobiao：HTTP 521 Cloudflare/WAF，需 WebBridge
- cebpub：详情 vaptcha，需人工过验证后复用会话
- chinabidding：详情登录墙，需账号 Cookie
"""
from __future__ import annotations

import re
import sys
from html import unescape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect  # noqa: E402

from crawl.config_loader import sources_cfg
from crawl.http_session import HttpSession


def _plain(html: str) -> str:
    t = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = unescape(t)
    return re.sub(r"\s+", " ", t).strip()


def _amount(text: str) -> tuple[float | None, str | None]:
    m = re.search(
        r"(?:总中标金额|中标（成交）金额|中标金额|成交金额|预算金额|采购预算)[:：]?\s*[￥¥]?\s*([\d,\.]+)\s*(万元|元|万)?",
        text,
    )
    if not m:
        return None, None
    num = float(m.group(1).replace(",", ""))
    unit = m.group(2) or "元"
    amount_text = m.group(1).replace(",", "") + " " + unit
    if unit in ("万元", "万"):
        return num * 10000, amount_text
    return num, amount_text


def _cn_date_to_iso(s: str) -> str | None:
    """中文日期规整为 MySQL DATETIME 可接受格式；规整不了返回 None。"""
    m = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日(?:[^\d]{0,4}(\d{1,2}):(\d{2}))?", s)
    if not m:
        return None
    y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
    hh, mm = m.group(4) or "00", m.group(5) or "00"
    return f"{y}-{mo}-{d} {hh}:{mm}:00"


def parse_ccgp_detail(html: str) -> dict:
    """解析 ccgp.gov.cn 详情页（开放、无验证码）。"""
    t = _plain(html)
    out: dict = {}

    def first(pats, key):
        for p in pats:
            m = re.search(p, t)
            if m:
                out[key] = m.group(1).strip()
                return

    first([r"项目编号[:：]\s*([A-Za-z0-9\-_/]{3,60})", r"采购项目编号[:：]\s*([A-Za-z0-9\-_/]{3,60})"], "project_code")
    first([r"采购单位[:：\s]+([^\s|]{2,40})", r"采购人[:：\s]+([^\s|]{2,40})"], "buyer")
    first([r"代理机构名称[:：\s]+([^\s|]{2,40})", r"采购代理机构[:：\s]+([^\s|]{2,40})"], "agency")
    amount, amount_text = _amount(t)
    if amount is not None:
        out["amount"] = amount
        out["amount_text"] = amount_text
    m = re.search(r"(?:投标截止时间|提交投标文件截止时间|开标时间|响应文件提交截止时间)[:：]\s*([\d\-年月日 :]{8,30})", t)
    if m:
        raw = m.group(1).strip()
        iso = _cn_date_to_iso(raw)
        if iso:
            out["deadline"] = iso
        elif re.fullmatch(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}([ T]\d{1,2}:\d{2}(:\d{2})?)?", raw):
            out["deadline"] = raw[:19].replace("/", "-")
    return out


def detail_sources() -> set[str]:
    """返回配置了详情抓取能力的源站 id。"""
    cfg = sources_cfg()
    return {sid for sid, sc in cfg.items() if sid != "defaults" and sc.get("detail")}


def fetch_detail(source_id: str, detail_url: str) -> dict:
    """抓取并解析详情字段；失败/不支持返回空 dict（或含 _error 的 dict）。"""
    if source_id == "ccgp":
        http = HttpSession("ccgp")
        try:
            _, raw, _ = http.request(detail_url, headers={"Referer": "https://www.ccgp.gov.cn/"})
        except Exception:
            return {}
        for enc in ("utf-8", "gbk", "gb2312"):
            try:
                html = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            html = raw.decode("utf-8", "ignore")
        return parse_ccgp_detail(html)
    if source_id == "chinabidding":
        # P3 已开发的采招 Cookie 详情模块（登录墙/异常如实带 _error）
        from crawl.sources.chinabidding_detail import fetch_detail_fields

        r = fetch_detail_fields(detail_url)
        if r.get("error"):
            return {"_error": str(r["error"])[:120]}
        if r.get("login_wall"):
            return {"_error": "login_wall"}
        out: dict = {}
        for k in ("project_code", "buyer", "agency"):
            v = r.get(k)
            if v and "立即注册" not in str(v):
                out[k] = str(v).strip()
        at = r.get("amount_text")
        if at and "立即注册" not in str(at):
            out["amount_text"] = str(at).strip()
            m = re.match(r"^([\d,\.]+)\s*(万元|万|元)?$", str(at).strip())
            if m:
                try:
                    num = float(m.group(1).replace(",", ""))
                except ValueError:
                    num = None
                if num is not None:
                    out["amount"] = num * 10000 if m.group(2) in ("万元", "万") else num
        return out
    # 其余站字段回填走按需桥路径（crawl/backfill.py），此处不支持
    return {}


def update_notice_detail(notice_id: int, fields: dict) -> None:
    allowed = {"amount", "amount_text", "buyer", "agency", "project_code", "deadline", "open_time", "notice_type"}
    sets: list[str] = []
    params: list = []
    for k, v in fields.items():
        if k in allowed and v is not None:
            sets.append(f"{k}=%s")
            params.append(v)
    if not sets:
        return
    params.append(notice_id)
    conn = connect(autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE notices SET {', '.join(sets)} WHERE id=%s", tuple(params))
    finally:
        conn.close()


def enrich_source_details(source_id: str, *, limit: int = 5) -> dict:
    """回填该源站最近缺失金额的详情字段。返回统计。"""
    if source_id not in detail_sources():
        return {"enabled": False}
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, detail_url FROM notices "
                "WHERE source_id=%s AND detail_url IS NOT NULL AND amount IS NULL "
                "ORDER BY created_at DESC LIMIT %s",
                (source_id, limit),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    enriched = 0
    for r in rows:
        fields = fetch_detail(source_id, r["detail_url"])
        if not fields:
            continue
        update_notice_detail(r["id"], fields)
        enriched += 1
    return {"enabled": True, "candidates": len(rows), "enriched": enriched}
