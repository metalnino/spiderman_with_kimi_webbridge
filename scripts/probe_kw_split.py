"""关键词拆分必要性探针（只读，不写库）：ccgp + chinabidding 第 1 页实测。

问题：新词「办公绿化/职场绿植绿化」直接爬够不够，还是需要拆成
「办公区绿化/办公室绿化/办公场所绿化…」变体词补召回？
判据：① 新词本身原始命中量；② 站点检索是否分词（查询「办公绿化」是否返回
「办公区绿化」类变体标题）——若分词，无需拆；若严格子串且变体词有货，才拆。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["SPIDER_CCGP_MAX_PAGES"] = "1"
os.environ["SPIDER_CHINABIDDING_MAX_PAGES"] = "1"

from crawl.sources.ccgp import CcgpSource  # noqa: E402
from crawl.sources.chinabidding import ChinabiddingSource  # noqa: E402
from crawl.sources.base import SourceError  # noqa: E402

ACTIVE = ["绿植租摆", "办公绿化", "职场绿植绿化"]
VARIANTS = ["办公区绿化", "办公室绿化", "办公场所绿化"]

out: dict = {"sites": {}}


def probe(site_key: str, src, kws: list[str]) -> None:
    site = {"keyword_results": {}}
    try:
        items = list(src.fetch(kws, max_pages=1))
        for kw in kws:
            rows = [n for n in items if n.keyword == kw]
            site["keyword_results"][kw] = {
                "count": len(rows),
                "titles": [
                    {"t": n.title, "d": (n.publish_date or "")[:10], "city": n.city}
                    for n in rows[:20]
                ],
            }
    except SourceError as e:
        site["error"] = str(e)[:300]
        site["partial_keyword_results"] = {
            kw: len([n for n in e.partial if n.keyword == kw]) for kw in kws
        }
    out["sites"][site_key] = site


probe("ccgp", CcgpSource(), ACTIVE)
probe("chinabidding", ChinabiddingSource(), ACTIVE + VARIANTS)

# 分词判据：查询「办公绿化」时返回的标题里是否出现变体拼写
for site in out["sites"].values():
    kwr = site.get("keyword_results") or {}
    base = kwr.get("办公绿化") or {}
    titles = [x["t"] for x in base.get("titles") or []]
    site["segment_evidence"] = {
        v: any(v in t for t in titles)
        for v in VARIANTS
    }

(ROOT / "data" / "kw_split_probe.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
)
print(json.dumps({
    "ccgp": {k: (v.get("count") if isinstance(v, dict) else v)
             for k, v in (out["sites"].get("ccgp") or {}).get("keyword_results", {}).items()},
    "chinabidding": {k: (v.get("count") if isinstance(v, dict) else v)
                     for k, v in (out["sites"].get("chinabidding") or {}).get("keyword_results", {}).items()},
    "errors": {k: v.get("error") for k, v in out["sites"].items() if v.get("error")},
}, ensure_ascii=False))
