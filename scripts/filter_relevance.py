"""Post-filter crawl items by dual-model agreed relevance rules."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "data" / "trial" / "items_enriched.json"
FILT = json.loads((ROOT / "config" / "relevance_filter.json").read_text(encoding="utf-8"))
CFG = json.loads((ROOT / "config" / "crawl_config.json").read_text(encoding="utf-8"))
OUT_DIR = ROOT / "data" / "trial"


def is_relevant(item: dict) -> tuple[bool, str]:
    title = item.get("title") or ""
    kw = item.get("keyword") or ""
    for n in FILT["negative_terms"]:
        if n in title:
            return False, f"negative:{n}"
    has_stem = any(s in title for s in FILT["positive_stems"])
    if kw in FILT.get("scene_keywords_need_stem", []) and not has_stem:
        return False, "scene_without_stem"
    if FILT.get("require_positive_stem") and not has_stem:
        return False, "no_positive_stem"
    return True, "ok"


def main() -> None:
    items = json.loads(ITEMS.read_text(encoding="utf-8"))
    kept, dropped = [], []
    reasons = {}
    for it in items:
        ok, why = is_relevant(it)
        if ok:
            kept.append(it)
        else:
            dropped.append({**it, "drop_reason": why})
            reasons[why] = reasons.get(why, 0) + 1

    # tighten active keywords in crawl config
    active_keep = [
        "绿植租摆",
        "花卉租摆",
        "室内绿化",
        "室外绿化",
        "绿化养护",
        "园林养护",
        "草坪养护",
        "足球场养护",
        "绿化管养",
        "物业绿化",
        "园区绿化",
        "苗木采购",
        "花卉采购",
        "立体绿化",
        "植物墙",
        "室内植物租赁",
    ]
    if isinstance(CFG.get("keywords"), dict):
        CFG["keywords"]["active"] = active_keep
        CFG["keywords"]["scene_as_tag_only"] = [
            "酒店绿植",
            "酒店绿化",
            "写字楼绿植",
            "办公楼绿化",
            "售楼处绿植",
            "商业综合体绿化",
            "商业空间绿化",
            "会所绿化",
            "大堂绿植",
            "屋顶绿化",
            "购物中心绿化",
            "商场绿植",
        ]
        CFG["notes"]["relevance"] = "场景词不再单独检索；标题需正茎词且过负向过滤"
        (ROOT / "config" / "crawl_config.json").write_text(
            json.dumps(CFG, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    (OUT_DIR / "items_relevant.json").write_text(json.dumps(kept, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT_DIR / "items_dropped.json").write_text(json.dumps(dropped, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "before": len(items),
        "kept": len(kept),
        "dropped": len(dropped),
        "drop_reasons": reasons,
        "open_kept": sum(1 for x in kept if x.get("bid_status_code") == "open"),
    }
    (OUT_DIR / "relevance_filter_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # rebuild a slim viewer from kept
    viewer = (OUT_DIR / "viewer.html").read_text(encoding="utf-8")
    import re

    viewer2 = re.sub(
        r"const DATA = \[.*?\];\nlet page = 1;",
        "const DATA = " + json.dumps(kept, ensure_ascii=False) + ";\nlet page = 1;",
        viewer,
        count=1,
        flags=re.S,
    )
    viewer2 = viewer2.replace(
        "HTTP 列表爬取 · 随机间隔防封 · 金额待详情验证码后补 · 「看详情」可能需验证",
        f"已做相关性过滤：保留 {len(kept)}/{len(items)} · 默认可投标 · 金额仍待补",
    )
    (OUT_DIR / "viewer_relevant.html").write_text(viewer2, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
