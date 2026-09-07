"""实体情报员契约/聚合/交接物单测（纯函数 + mock，不碰外网/DB）。"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from crawl import entity_aggregate as ea  # noqa: E402
from crawl import intel_employee as ie  # noqa: E402


def _notice(nid, buyer, title, city, pub, keyword="绿植租摆", source_id="ccgp",
            original_url=None, origin_source=None, stage="bidding", summary=None):
    return {
        "id": nid, "buyer": buyer, "title": title, "city": city, "province": "江苏",
        "publish_date": pub, "created_at": pub, "keyword": keyword, "source_id": source_id,
        "original_url": original_url, "origin_source": origin_source,
        "notice_stage": stage, "project_key": f"pk{nid}", "project_name": title,
        "summary": summary, "detail_url": f"https://x/{nid}", "official_url": None, "winner": None,
    }


class TestValidateInput(unittest.TestCase):
    def test_defaults(self):
        n = ie.validate_input(None)
        self.assertEqual(n["dateRange"], None)
        self.assertEqual(n["regionFilter"], None)
        self.assertEqual(n["platforms"], None)
        self.assertTrue(n["extractWinners"])

    def test_full_input(self):
        n = ie.validate_input({
            "dateRange": {"start": "2026-01-01", "end": "2026-12-31"},
            "regionFilter": ["南京", "苏州"],
            "platforms": ["ccgp", "ggzy"],
            "extractWinners": False,
        })
        self.assertEqual(n["dateRange"]["start"], "2026-01-01")
        self.assertEqual(n["regionFilter"], ["南京", "苏州"])
        self.assertFalse(n["extractWinners"])

    def test_invalid_date_range(self):
        with self.assertRaises(ie.ContractInputError):
            ie.validate_input({"dateRange": "2026-01-01"})

    def test_invalid_region(self):
        with self.assertRaises(ie.ContractInputError):
            ie.validate_input({"regionFilter": "南京"})

    def test_invalid_extract_winners(self):
        with self.assertRaises(ie.ContractInputError):
            ie.validate_input({"extractWinners": "yes"})


class TestEstimateNextBid(unittest.TestCase):
    def _times(self, *ds):
        return [datetime.strptime(d, "%Y-%m-%d") for d in ds]

    def test_insufficient_samples(self):
        self.assertEqual(ea.estimate_next_bid([]), {"hint": None, "median_days": None, "next_date": None, "confidence": None})
        self.assertEqual(
            ea.estimate_next_bid(self._times("2026-01-01"))["hint"], None,
        )

    def test_low_confidence_three_samples(self):
        est = ea.estimate_next_bid(self._times("2026-03-01", "2026-06-01", "2026-09-01"))
        self.assertEqual(est["median_days"], 92)
        self.assertEqual(est["confidence"], "low")
        self.assertEqual(est["next_date"], "2026-12-02")
        self.assertIn("下次约", est["hint"])

    def test_medium_confidence(self):
        est = ea.estimate_next_bid(self._times(
            "2026-01-01", "2026-04-01", "2026-07-01", "2026-10-01", "2027-01-01",
        ))
        self.assertEqual(est["confidence"], "medium")


class TestAggregateEntities(unittest.TestCase):
    def test_aggregate_and_merge(self):
        notices = [
            _notice(1, "南京某医院", "南京某医院绿植租摆服务采购项目", "南京", "2026-03-01"),
            _notice(2, "南京某医院", "南京某医院绿植租摆服务采购项目(二次)", "南京", "2026-06-01"),
            _notice(3, "南京某医院", "南京某医院绿化养护项目", "南京", "2026-09-01",
                    original_url="https://www.ccgp.gov.cn/", origin_source="中国政府采购网"),
            _notice(4, "南京某物业公司", "南京某物业公司绿植租摆项目", "南京", "2026-04-01"),
            _notice(5, "南京某物业公司", "南京某物业公司绿植租摆项目", "南京", "2026-08-01"),
        ]
        entities = ea.aggregate_entities(notices)
        self.assertEqual(len(entities), 2)
        hospital = next(e for e in entities if e["name"] == "南京某医院")
        self.assertEqual(hospital["entityType"], "buyer")
        self.assertEqual(hospital["noticeCount"], 3)  # 3 个不同标题
        self.assertEqual(hospital["lastNoticeAt"], "2026-09-01T00:00:00")
        self.assertEqual(hospital["nextBidConfidence"], "low")
        self.assertEqual(hospital["officialChannels"], ["https://www.ccgp.gov.cn/"])
        self.assertEqual(hospital["originSources"], ["中国政府采购网"])
        self.assertEqual(hospital["serviceTags"], [{"k": "绿植租摆", "n": 3}])
        # 同标题同城折叠：物业公司 2 条只算 1
        prop = next(e for e in entities if e["name"] == "南京某物业公司")
        self.assertEqual(prop["noticeCount"], 1)

    def test_buyer_fallback_from_title(self):
        notices = [
            _notice(1, None, "南京市第一医院绿植租摆服务采购", "南京", "2026-03-01"),
        ]
        entities = ea.aggregate_entities(notices)
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["name"], "南京市第一医院")

    def test_normalize_merge_same_key(self):
        self.assertEqual(ea.normalize_entity_key("南京景天园林有限公司"), ea.normalize_entity_key("南京景天园林有限责任公司"))


class TestExtractWinnersAndRelations(unittest.TestCase):
    def test_extract_winners(self):
        notices = [
            _notice(1, "南京某医院", "某项目中标结果公告", "南京", "2026-09-01", stage="result",
                    summary="中标供应商：某园林工程有限公司"),
            _notice(2, "某医院", "某项目结果公告", "南京", "2026-09-02", stage="result",
                    summary="如需查看详细内容，请先免费注册"),
            _notice(3, "某医院", "某项目招标公告", "南京", "2026-09-03", stage="bidding",
                    summary="中标供应商：不应抽取"),
        ]
        wres = ie.extract_winners(notices)
        self.assertEqual(wres["stats"], {"result_total": 2, "extracted": 1, "rate": 0.5})
        self.assertEqual(len(wres["winners"]), 1)
        w = wres["winners"][0]
        self.assertEqual(w["name"], "某园林工程有限公司")
        self.assertEqual(w["buyer"], "南京某医院")
        self.assertEqual(w["projectKey"], "pk1")
        self.assertEqual(w["extractSource"], "summary")

    def test_build_relations(self):
        winners = [
            {"name": "某园林工程有限公司", "buyer": "南京某医院", "projectKey": "pk1"},
            {"name": "某园林工程有限公司", "buyer": "南京某医院", "projectKey": "pk1"},  # 重复
            {"name": "某花卉公司", "buyer": "某物业", "projectKey": None},
        ]
        rels = ie.build_relations(winners)
        self.assertEqual(len(rels), 2)
        self.assertEqual(rels[0], {"buyer": "南京某医院", "winner": "某园林工程有限公司", "projectKey": "pk1"})


class TestIntelHandoff(unittest.TestCase):
    def test_handoff_writes_latest_and_archive(self):
        spec = importlib.util.spec_from_file_location("intel_run", ROOT / "scripts" / "intel_run.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fake = {
            "output": {
                "entities": [{"name": "南京某医院", "noticeCount": 3}],
                "winners": [{"name": "某园林工程有限公司"}],
                "relations": [{"buyer": "南京某医院", "winner": "某园林工程有限公司"}],
            },
            "report": {"runId": "intel-20260823T000000"},
        }
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(mod, "HANDOFF_DIR", Path(td) / "handoffs" / "intel"):
                latest = mod._write_handoff(fake)
            self.assertTrue(Path(latest).exists())
            payload = json.loads(Path(latest).read_text(encoding="utf-8"))
            self.assertEqual(payload["runId"], "intel-20260823T000000")
            self.assertEqual(payload["implements"], "entity_intel/v1.0.0")
            self.assertEqual(payload["entities"], fake["output"]["entities"])
            self.assertEqual(payload["winners"], fake["output"]["winners"])
            self.assertEqual(payload["relations"], fake["output"]["relations"])
            archive = Path(td) / "handoffs" / "intel" / "intel-20260823T000000.json"
            self.assertTrue(archive.exists())


if __name__ == "__main__":
    unittest.main()
