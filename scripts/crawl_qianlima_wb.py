"""qianlima（千里马招标网）WebBridge 爬取：搜索 API 直调 HTTP 418 反爬（站点级，改 UA 无效）。

路径：真浏览器打开 search.qianlima.com 搜索页 → 页面上下文内 fetch POST 同款搜索接口
      （继承页面 Cookie/JS 环境）→ 带回 JSON → 复用 QianlimaSource._parse（与 HTTP 版契约一致：
      Notice 字段 / keyword / 城市 match_city / external_id=contentid 去重）。
详情：bid-<id>.html 419 反爬 → 详情仍走桥（DETAIL_MODES qianlima=bridge，可空），本模块只负责列表。

本机运行（需 Kimi 浏览器扩展已连桥）。员工外壳按 BROWSER_ROUTES 调用 main(keywords)。
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crawl import webbridge_client as wb  # noqa: E402
from crawl.config_loader import only_target_cities, publish_date_range, target_city_names  # noqa: E402
from crawl.db_store import finish_run, start_run, upsert_notices  # noqa: E402
from crawl.keywords import enabled_keywords  # noqa: E402
from crawl.models import Notice  # noqa: E402
from crawl.sources.qianlima import QianlimaSource  # noqa: E402

HOME = "https://search.qianlima.com/"
SESSION = "qianlima-crawl"

# 站点级 WAF 硬拦截特征（2026-08-25 实网探针：真人浏览器 + 站内 SPA 自身请求同样 418，
# 属 IP/设备风控而非模拟不足；命中即停手，不轰炸剩余词）
WAF_BLOCK_MARKERS = ("418", "疑似恶意攻击", "cloudwaf")


def _is_waf_block(err: str) -> bool:
    s = (err or "").lower()
    return any(m in s for m in ("418", "疑似恶意攻击", "cloudwaf"))


def build_search_url(kw: str, page: int = 1) -> str:
    """与 HTTP 版 QianlimaSource._build_url 完全一致（同款搜索 API）。"""
    return QianlimaSource()._build_url(kw, page)


def search_page_url(kw: str) -> str:
    """搜索页 URL（与 HTTP 版 Referer 一致），先落地页面上下文再页内 fetch。"""
    from urllib.parse import quote

    return f"{HOME}?q={quote(kw)}"


def fetch_search_js(url: str) -> str:
    """页面上下文内 fetch POST 同款搜索 API 的 JS（IIFE 返回 Promise，桥 evaluate 会 await）。"""
    return (
        "(async () => {"
        " const url = " + json.dumps(url) + ";"
        " try {"
        "  const resp = await fetch(url, {method: 'POST', body: '', credentials: 'include',"
        "   headers: {'Content-Type': 'application/json', 'Accept': 'application/json, text/plain, */*'}});"
        "  const text = await resp.text();"
        "  return JSON.stringify({status: resp.status, text: text});"
        " } catch (e) { return JSON.stringify({status: 0, text: '', error: String(e).slice(0, 200)}); }"
        "})()"
    )


def _err_text(e) -> str:
    if e is None:
        return ""
    if isinstance(e, str):
        return e
    if isinstance(e, dict):
        return str(e.get("message") or e.get("code") or e)
    return str(e)


def search_page(kw: str, page: int = 1) -> dict:
    """页内 fetch 搜索 API，返回解析后的 JSON dict；失败抛 RuntimeError（诚实带状态/片段）。"""
    url = build_search_url(kw, page)
    r = wb.evaluate(fetch_search_js(url), session=SESSION)
    if not r.get("ok"):
        raise RuntimeError(f"bridge_evaluate_failed: {_err_text(r.get('error'))[:120]}")
    val = (r.get("data") or {}).get("value")
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            val = None
    if not isinstance(val, dict):
        raise RuntimeError(f"bridge evaluate malformed: {str(val)[:200]}")
    status = val.get("status")
    if status not in (200, "200"):
        snippet = (val.get("text") or val.get("error") or "").strip()
        raise RuntimeError(f"search http={status}: {snippet[:200]}")
    text = (val.get("text") or "").strip()
    if not text:
        raise RuntimeError("search empty body")
    try:
        data = json.loads(text)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"search json parse: {str(e)[:120]}") from e
    if not isinstance(data, dict) or str(data.get("code")) != "200":
        raise RuntimeError(
            f"search api code={data.get('code') if isinstance(data, dict) else None} "
            f"msg={data.get('msg') if isinstance(data, dict) else None}"
        )
    return data


def parse_payload(data: dict, kw: str) -> list[Notice]:
    """复用 QianlimaSource._parse（Notice 字段/城市 match_city/external_id=contentid 去重契约）。"""
    return QianlimaSource()._parse(data, kw)


def _filter_notices(notices: list[Notice]) -> tuple[list[Notice], int]:
    """城市/发布时间过滤（与 HTTP 内核 runner.run_source 口径一致），返回 (kept, dropped)。"""
    total = len(notices)
    if only_target_cities():
        targets = set(target_city_names())
        notices = [n for n in notices if (n.city or "") in targets]
    pmin, pmax = publish_date_range()
    if pmin or pmax:
        kept = []
        for n in notices:
            pub = (n.publish_date or "")[:10]
            if not pub:
                kept.append(n)  # 无日期不因范围丢弃（与内核一致）
            elif (not pmin or pub >= pmin) and (not pmax or pub <= pmax):
                kept.append(n)
        notices = kept
    return notices, total - len(notices)


def human_pause(min_s: float = 2.0, max_s: float = 6.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


MOUSE_JS = r"""(() => {
  let x = 200 + Math.random() * 400, y = 200 + Math.random() * 400;
  for (let i = 0; i < 8; i++) {
    x += (Math.random() - 0.5) * 90;
    y += (Math.random() - 0.5) * 90;
    document.dispatchEvent(new MouseEvent('mousemove', {clientX: x, clientY: y, bubbles: true}));
  }
  return 'ok';
})()"""


def main(keywords: list[str] | None = None) -> dict:
    """返回 {status, error, notices:[dict含content_hash]}（员工外壳路由调用）。

    status：success / partial（部分词失败但已有入库结果） / failed。
    部分结果绝不丢弃：每词独立 try，失败记 first_err 继续下一词，已采公告全部入库。
    """
    from dataclasses import asdict

    kws = list(keywords) if keywords else enabled_keywords()
    if not wb.available():
        # 诚实记账：桥不在线也留一条 failed run，避免台账「假 0」无自证
        run_id = start_run("qianlima")
        finish_run(run_id, status="failed", item_count=0, note="webbridge_not_available")
        print(json.dumps({"ok": False, "error": "webbridge_not_available", "hint": "请打开 Kimi 浏览器扩展"}, ensure_ascii=False))
        return {"status": "failed", "error": "webbridge_not_available", "notices": []}

    run_id = start_run("qianlima")
    all_notices: list[Notice] = []
    first_err: str | None = None
    try:
        for i, kw in enumerate(kws):
            if i > 0:
                human_pause(3.0, 8.0)  # 词间随机停顿，防连发限流
            try:  # 单词语义隔离：一词失败不拖垮整轮，已采部分保留
                # 复用同一标签页（new_tab 仅首个词），避免浏览器堆积 20 个标签
                wb.navigate(search_page_url(kw), session=SESSION, group_title="qianlima-crawl", new_tab=(i == 0))
                human_pause(2.0, 3.5)  # 等页面 JS/风控初始化
                data = search_page(kw, page=1)
                items = parse_payload(data, kw)
                print(f"[qianlima-wb] {kw} items={len(items)}", flush=True)
                all_notices.extend(items)
                try:
                    wb.evaluate(MOUSE_JS, session=SESSION)
                except Exception:  # noqa: BLE001
                    pass
            except Exception as e:  # noqa: BLE001
                if first_err is None:
                    first_err = f"qianlima search failed: {str(e)[:200]}"
                print(f"[qianlima-wb] {kw} error: {e}", flush=True)
                if _is_waf_block(str(e)):
                    # 站点级 418 硬拦截：立即停手，剩余词不再打（频控靠冷却阶梯不靠轰炸）；
                    # 下轮调度仍会探 1 词做自愈探测，解封即恢复产出。
                    first_err = (
                        f"qianlima waf_block(418 site-level, stopped after {i + 1}/{len(kws)} words): "
                        f"{str(e)[:160]}"
                    )
                    break

        kept, dropped = _filter_notices(all_notices)
        stats = upsert_notices(kept)
        status = "failed" if (first_err and not kept) else ("partial" if first_err else "success")
        note = (
            f"qianlima-wb raw={len(all_notices)} kept={len(kept)} city_date_drop={dropped} "
            f"upsert≈{stats['affected']} err={first_err or ''}"
        )[:500]
        finish_run(run_id, status=status, item_count=stats["attempted"], note=note)
        print(json.dumps({"status": status, "items": len(kept), **stats}, ensure_ascii=False))
        return {
            "status": status,
            "error": first_err,
            "notices": [{**asdict(n), "content_hash": n.content_hash()} for n in kept],
        }
    except Exception as e:  # noqa: BLE001
        finish_run(run_id, status="failed", item_count=0, note=str(e)[:500])
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return {"status": "failed", "error": str(e)[:300], "notices": []}
    finally:
        # 用完关 tab，避免浏览器堆积标签页吃内存卡死
        try:
            closed = wb.close_group("qianlima-crawl", session=SESSION)
            if closed:
                print(f"[qianlima-wb] closed {closed} tabs", flush=True)
        except Exception:
            pass


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", default="", help="comma keywords; empty=all enabled")
    args = ap.parse_args()
    kws = [k.strip() for k in args.keywords.split(",") if k.strip()] or None
    main(kws)
