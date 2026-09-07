"""采集员详情补全入口编排单测（mock DB/backfill/AI，不碰外网/DB）。"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _load():
    spec = importlib.util.spec_from_file_location("collector_detail", ROOT / "scripts" / "collector_detail.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestCollectorDetailOrchestration(unittest.TestCase):
    def test_run_and_trace(self):
        mod = _load()
        cands = [
            {"id": 1, "source_id": "yfbzb", "title": "某医院绿植租摆招标公告"},
            {"id": 2, "source_id": "yfbzb", "title": "某物业绿植项目"},
            {"id": 3, "source_id": "tgnet", "title": "某工程"},
        ]

        def fake_backfill(nid):
            return {"ok": True, "error": None, "original_url": "https://www.ccgp.gov.cn/x",
                    "origin_source": "中国政府采购网", "origin_fetched": True}

        def fake_ai(nid):
            return {"ok": True, "filled": ["buyer"], "ai_fields": {"buyer": "某医院"}}

        with mock.patch.object(mod, "_candidates", return_value=cands), \
                mock.patch.object(mod, "backfill_notice", side_effect=fake_backfill), \
                mock.patch.object(mod, "ai_enrich_notice", side_effect=fake_ai):
            stats = mod.run(limit_total=5, per_source_limit=2, use_ai=True)
        self.assertEqual(stats["processed"], 3)
        self.assertEqual(stats["detail_ok"], 3)
        self.assertEqual(stats["ai_ok"], 3)
        self.assertEqual(len(stats["traces"]), 3)
        t = stats["traces"][0]
        self.assertEqual(t["source_id"], "yfbzb")
        self.assertEqual(t["detail"]["origin_url"], "https://www.ccgp.gov.cn/x")
        self.assertTrue(t["detail"]["origin_fetched"])
        self.assertEqual(t["ai"]["filled"], ["buyer"])

    def test_per_source_cap(self):
        mod = _load()
        cands = [{"id": i, "source_id": "yfbzb", "title": f"t{i}"} for i in range(1, 6)]

        def fake_backfill(nid):
            return {"ok": True, "error": None}

        def fake_ai(nid):
            return {"ok": False, "error": "ai_empty"}

        with mock.patch.object(mod, "_candidates", return_value=cands), \
                mock.patch.object(mod, "backfill_notice", side_effect=fake_backfill), \
                mock.patch.object(mod, "ai_enrich_notice", side_effect=fake_ai):
            stats = mod.run(limit_total=10, per_source_limit=2, use_ai=True)
        self.assertEqual(stats["processed"], 2)  # 每站封顶 2，5 条 yfbzb 只处理 2
        self.assertEqual(stats["ai_failed"], 2)

    def test_no_ai(self):
        mod = _load()
        cands = [{"id": 1, "source_id": "yfbzb", "title": "t"}]

        def fake_backfill(nid):
            return {"ok": True, "error": None}

        with mock.patch.object(mod, "_candidates", return_value=cands), \
                mock.patch.object(mod, "backfill_notice", side_effect=fake_backfill), \
                mock.patch.object(mod, "ai_enrich_notice") as fake_ai:
            stats = mod.run(limit_total=5, per_source_limit=2, use_ai=False)
        self.assertEqual(stats["processed"], 1)
        fake_ai.assert_not_called()
        self.assertNotIn("ai", stats["traces"][0])


if __name__ == "__main__":
    unittest.main()
