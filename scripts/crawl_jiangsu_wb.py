"""jiangsu_zhaobiao WebBridge 爬取（JSL 两阶段反爬需真实浏览器；本机运行，需 Kimi 扩展连接）。"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crawl import webbridge_client as wb  # noqa: E402
from crawl.db_store import finish_run, start_run, upsert_notices  # noqa: E402
from crawl.keywords import enabled_keywords  # noqa: E402
from crawl.models import Notice  # noqa: E402

HOME = "https://jiangsu.zhaobiao.cn"
SESSION = "jiangsu-crawl"

EXTRACT_JS = r"""(() => {
  const out = [];
  const seen = {};
  document.querySelectorAll('a').forEach(a => {
    const href = a.getAttribute('href') || '';
    const m = href.match(/([a-z]+)_v_([0-9a-f]{16,})/i);
    if (!m) return;
    if (seen[m[2]]) return;
    seen[m[2]] = 1;
    const row = a.closest('li,tr,div') || a.parentElement;
    out.push({href: href, kind: m[1].toLowerCase(), ext: m[2],
              title: (a.textContent||'').replace(/\s+/g,' ').trim(),
              row: (row && row.innerText || '').replace(/\s+/g,' ')});
  });
  return JSON.stringify(out);
})()"""


def human_pause(min_s: float = 2.0, max_s: float = 6.0) -> None:
    """随机停顿，降低机器特征。"""
    time.sleep(random.uniform(min_s, max_s))


# 尽力而为的轻量鼠标移动（合成事件 isTrusted=false；被检测也无害）
MOUSE_JS = r"""(() => {
  let x = 200 + Math.random() * 400, y = 200 + Math.random() * 400;
  for (let i = 0; i < 8; i++) {
    x += (Math.random() - 0.5) * 90;
    y += (Math.random() - 0.5) * 90;
    document.dispatchEvent(new MouseEvent('mousemove', {clientX: x, clientY: y, bubbles: true}));
  }
  return 'ok';
})()"""


def search_url(kw: str, page: int = 1) -> str:
    q = f"page={page}&attachment=1&channels=&area=&field=all&queryword={urllib.parse.quote(kw)}"
    return f"{HOME}/psearch/Dqsearch?{q}"


def match_city(title: str) -> str | None:
    from crawl.config_loader import cities

    hits = [c["name"] for c in cities() if c["name"] in (title or "")]
    return hits[0] if hits else None


def extract_results() -> list[dict]:
    r = wb.evaluate(EXTRACT_JS, session=SESSION)
    val = (r.get("data") or {}).get("value")
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return []
    return val or []


def wait_results(timeout: int = 60) -> list[dict]:
    for _ in range(max(1, timeout // 5)):
        time.sleep(5)
        items = extract_results()
        if items:
            return items
    return []


def parse_items(raw: list[dict], kw: str) -> list[Notice]:
    from crawl.config_loader import only_target_cities, publish_date_range, target_city_names

    targets = set(target_city_names())
    pmin, pmax = publish_date_range()
    notices: list[Notice] = []
    for it in raw:
        title = (it.get("title") or "").strip()
        row = (it.get("row") or "").strip()
        if len(title) < 6:
            continue
        pub = None
        mp = re.search(r"[（(]\s*(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}(?:[ T]\d{1,2}:\d{1,2}(?::\d{1,2})?)?)\s*[)）]\s*$", title)
        if mp:
            pub = mp.group(1).replace("/", "-").replace(".", "-")[:19]
            title = title[:mp.start()].strip()
        else:
            dates = re.findall(r"(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})", row)
            if dates:
                pub = dates[-1].replace("/", "-").replace(".", "-")
        city = match_city(row + " " + title)
        # 8 城 + 发布时间范围过滤（与 HTTP 流程一致）
        if only_target_cities() and city not in targets:
            continue
        if pmin and pub and pub[:10] < pmin:
            continue
        if pmax and pub and pub[:10] > pmax:
            continue
        ext = it.get("ext") or ""
        notices.append(
            Notice(
                source_id="jiangsu_zhaobiao",
                source_name="江苏招标网",
                external_id=f"{it.get('kind') or 'item'}_{ext}",
                title=title,
                publish_date=pub,
                province="江苏",
                city=city,
                region_text="江苏",
                keyword=kw,
                notice_type=it.get("kind"),
                detail_url=it.get("href"),
                official_url=it.get("href"),
                bid_status="未知",
            )
        )
    return notices


def main(keywords: list[str] | None = None) -> dict:
    """返回 {status, error, notices:[dict含content_hash]}。员工外壳（collector/v1.0.0）路由调用；
    纯增量：CLI 入口忽略返回值，行为不变。"""
    from dataclasses import asdict

    kws = keywords or enabled_keywords()
    if not wb.available():
        # 诚实记账：桥不在线也留一条 failed run，避免台账「假 0」无自证
        run_id = start_run("jiangsu_zhaobiao")
        finish_run(run_id, status="failed", item_count=0, note="webbridge_not_available")
        print(json.dumps({"ok": False, "error": "webbridge_not_available", "hint": "请打开 Kimi 浏览器扩展"}, ensure_ascii=False))
        return {"status": "failed", "error": "webbridge_not_available", "notices": []}
    run_id = start_run("jiangsu_zhaobiao")
    all_notices: list[Notice] = []
    upserted = 0  # 增量落库累计（attempted 行数），中途被杀也能自证「采到过什么」
    try:
        # 暖场：先访问首页（模拟真人浏览入口），随机停留
        nav = wb.navigate(HOME, session=SESSION, group_title="jiangsu-crawl", new_tab=True)
        if isinstance(nav, dict) and nav.get("ok") is False:
            # 桥/扩展掉线：立即失败，不再对每个词空等 60s（原会 = 词数 × 60s）
            raise RuntimeError(f"bridge_unavailable: {str(nav.get('error'))[:160]}")
        human_pause(2.0, 5.0)
        empty_streak = 0
        for i, kw in enumerate(kws):
            if i > 0:
                human_pause(3.0, 8.0)  # 关键词之间随机停顿，防连发限流
            # 复用同一标签页（new_tab=False），避免浏览器里堆积 16 个标签
            nav = wb.navigate(search_url(kw), session=SESSION, group_title="jiangsu-crawl", new_tab=False)
            if isinstance(nav, dict) and nav.get("ok") is False:
                # 桥/扩展掉线：立即停（自愈）。不检查的话会「0 结果还空等 42 词 × 60s ≈ 47 分钟」
                print(f"[jiangsu-wb] 导航失败，提前停止: {str(nav.get('error'))[:120]}", flush=True)
                break
            human_pause(1.0, 2.5)
            raw = wait_results()
            notices = parse_items(raw, kw)
            print(f"[jiangsu-wb] {kw} items={len(notices)}", flush=True)
            all_notices.extend(notices)
            if notices:
                # 增量落库（2026-09-19）：外部终结/掉电/任务被杀时，已采部分必须留在库里。
                # 原实现把 upsert 放在整个词循环之后 —— 09-19 00:39 那轮采了 29 个词（真实条数
                # 18/10/5/24/…），进程被外部杀掉后一条都没入库（notices 里江苏当天更新 0 条）。
                try:
                    upserted += int(upsert_notices(notices).get("attempted") or 0)
                except Exception as e:  # noqa: BLE001 —— 落库失败只记录，不中断采集
                    print(f"[jiangsu-wb] 增量落库失败(继续采集): {str(e)[:120]}", flush=True)
            if not raw:
                empty_streak += 1
                if empty_streak >= 3:
                    print(f"[jiangsu-wb] 连续 {empty_streak} 个词无结果 → 提前停止（原会空等 {len(kws)} 词 × 60s）", flush=True)
                    break
            else:
                empty_streak = 0
            # 轻量模拟鼠标行为
            try:
                wb.evaluate(MOUSE_JS, session=SESSION)
            except Exception:
                pass
        stats = upsert_notices(all_notices)  # 幂等兜底（与增量重复不新增行）
        total = max(upserted, int(stats.get("attempted") or 0))
        finish_run(run_id, status="success", item_count=total,
                   note=f"jiangsu-wb items={len(all_notices)} incremental={upserted}")
        print(json.dumps({"items": len(all_notices), "incremental": upserted, **stats}, ensure_ascii=False))
        return {
            "status": "success",
            "error": None,
            "notices": [{**asdict(n), "content_hash": n.content_hash()} for n in all_notices],
        }
    except Exception as e:  # noqa: BLE001
        # 已增量落库的部分必须如实上报（partial），绝不报成 0 —— 否则台账出现「假 0」
        finish_run(run_id, status=("partial" if upserted else "failed"), item_count=upserted,
                   note=f"jiangsu-wb aborted, incremental={upserted}: {str(e)[:300]}")
        print(json.dumps({"ok": False, "error": str(e), "incremental": upserted}, ensure_ascii=False))
        return {
            "status": "partial" if upserted else "failed",
            "error": str(e)[:300],
            "notices": [{**asdict(n), "content_hash": n.content_hash()} for n in all_notices],
        }
    finally:
        # 用完关 tab，避免浏览器堆积标签页吃内存卡死
        try:
            closed = wb.close_group("jiangsu-crawl", session=SESSION)
            if closed:
                print(f"[jiangsu-wb] closed {closed} tabs", flush=True)
        except Exception:
            pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", default="", help="comma keywords; empty=all enabled")
    args = ap.parse_args()
    kws = [k.strip() for k in args.keywords.split(",") if k.strip()] or None
    main(kws)
