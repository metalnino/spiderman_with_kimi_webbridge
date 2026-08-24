"""全量词库审计探针（只读，不写库）：对词库所有分组 + 候选同义词做 chinabidding 第 1 页实测。

产出 data/kw_library_probe.json：
{words: {词: {count, cities, sample:[{t,d,city}] | error}}}
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["SPIDER_CHINABIDDING_MAX_PAGES"] = "1"

from crawl.config_loader import crawl_cfg  # noqa: E402
from crawl.sources.chinabidding import ChinabiddingSource  # noqa: E402
from crawl.sources.base import SourceError  # noqa: E402

cfg = crawl_cfg()
kw = cfg["keywords"]
LIB = []
for g in ("core", "scene", "commercial"):
    LIB += kw.get(g) or []
LIB += kw.get("active") or []
# 候选同义词/变体（拆分调优备选，实测后决定）
EXTRA = ["绿植养护", "植物租赁", "摆花", "花卉租赁", "绿植摆放", "室内绿植", "绿植服务", "绿化租摆"]
seen = set()
WORDS = []
for w in LIB + EXTRA:
    if w and w not in seen:
        seen.add(w)
        WORDS.append(w)

src = ChinabiddingSource()
out: dict = {"site": "chinabidding", "probe_words": len(WORDS), "words": {}}
for w in WORDS:
    try:
        items = list(src.fetch([w], max_pages=1))
    except SourceError as e:
        out["words"][w] = {"error": str(e)[:200]}
        continue
    rows = [n for n in items if n.keyword == w]
    out["words"][w] = {
        "count": len(rows),
        "target_city_hits": sorted({n.city for n in rows if n.city}),
        "sample": [{"t": n.title, "d": (n.publish_date or "")[:10]} for n in rows[:6]],
    }

(ROOT / "data" / "kw_library_probe.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
)
zero = sum(1 for v in out["words"].values() if v.get("count") == 0)
errs = sum(1 for v in out["words"].values() if "error" in v)
full = sum(1 for v in out["words"].values() if (v.get("count") or 0) >= 15)
print(json.dumps({"words": len(WORDS), "zero": zero, "page1_full": full, "errors": errs}, ensure_ascii=False))
