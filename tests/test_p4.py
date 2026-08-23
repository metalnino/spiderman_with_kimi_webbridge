"""P4 折叠 / 阶段筛选 / 详情 / 回填解析 单测（不依赖外网）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


class TestFold(unittest.TestCase):
    def test_fold_same_title_city(self):
        from crawl.ledger_data import _fold_notices

        rows = [
            {"id": 1, "title": "某项目 绿植租摆  结果公告", "city": "南京", "source_id": "a", "amount": None,
             "publish_date": "2026-08-10 00:00:00", "created_at": "2026-08-10 09:00:00", "detail_url": "u1"},
            {"id": 2, "title": "某项目绿植租摆结果公告", "city": "南京", "source_id": "b", "amount": 120000.0,
             "publish_date": "2026-08-11 00:00:00", "created_at": "2026-08-11 09:00:00", "detail_url": "u2"},
        ]
        out = _fold_notices(rows, "created")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["id"], 2)  # 有金额者为主行
        self.assertEqual(out[0]["dup_count"], 2)
        self.assertEqual(out[0]["sources"], ["a", "b"])
        self.assertEqual(len(out[0]["duplicates"]), 1)
        self.assertEqual(out[0]["duplicates"][0]["id"], 1)

    def test_no_fold_different_city(self):
        from crawl.ledger_data import _fold_notices

        rows = [
            {"id": 1, "title": "某项目结果公告", "city": "南京", "source_id": "a", "amount": None,
             "publish_date": None, "created_at": "2026-08-10 09:00:00", "detail_url": "u1"},
            {"id": 2, "title": "某项目结果公告", "city": "武汉", "source_id": "b", "amount": None,
             "publish_date": None, "created_at": "2026-08-11 09:00:00", "detail_url": "u2"},
        ]
        out = _fold_notices(rows, "created")
        self.assertEqual(len(out), 2)

    def test_no_fold_different_title_same_project(self):
        # 同项目不同阶段（标题不同）不折叠——时间线负责串
        from crawl.ledger_data import _fold_notices

        rows = [
            {"id": 1, "title": "某项目招标公告", "city": "南京", "source_id": "a", "amount": None,
             "publish_date": None, "created_at": "2026-08-10 09:00:00", "detail_url": "u1"},
            {"id": 2, "title": "某项目结果公告", "city": "南京", "source_id": "a", "amount": None,
             "publish_date": None, "created_at": "2026-08-11 09:00:00", "detail_url": "u2"},
        ]
        out = _fold_notices(rows, "created")
        self.assertEqual(len(out), 2)


class TestLedgerApiP4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        from crawl.api import app

        cls.client = TestClient(app)

    def test_meta_has_stages(self):
        body = self.client.get("/api/meta").json()
        stages = [s["key"] for s in body.get("stages", [])]
        self.assertIn("bidding", stages)
        self.assertIn("result", stages)
        self.assertIn("terminated", stages)

    def test_notices_folded_structure(self):
        r = self.client.get("/api/notices", params={"limit": "200"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body.get("folded"))
        self.assertEqual(body["total"], len(body["items"]))
        for it in body["items"]:
            if it.get("dup_count"):
                self.assertGreaterEqual(it["dup_count"], 2)
                # sources 是去重后的源站列表；同源站内重复时唯一源数 < 行数
                self.assertGreaterEqual(len(it["sources"]), 1)
                self.assertLessEqual(len(it["sources"]), it["dup_count"])
                self.assertEqual(len(it["duplicates"]), it["dup_count"] - 1)

    def test_stage_filter(self):
        r = self.client.get("/api/notices", params={"stage": "result", "limit": "200"})
        self.assertEqual(r.status_code, 200)
        for it in r.json()["items"]:
            self.assertEqual(it.get("notice_stage"), "result")

    def test_detail_and_timeline(self):
        # 先拿一条有 project_key 的行
        lst = self.client.get("/api/notices", params={"limit": "200"}).json()["items"]
        target = next((i for i in lst if i.get("dup_count")), None) or (lst[0] if lst else None)
        if target is None:
            self.skipTest("empty db")
        r = self.client.get(f"/api/notices/{target['id']}")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("notice", body)
        self.assertIn("timeline", body)
        self.assertEqual(body["notice"]["id"], target["id"])

    def test_detail_404(self):
        r = self.client.get("/api/notices/0")
        self.assertEqual(r.status_code, 404)

    def test_export_has_stage_column(self):
        r = self.client.get("/api/notices/export")
        self.assertEqual(r.status_code, 200)
        self.assertIn("阶段", r.text.splitlines()[0])

    def test_backfill_not_found_no_network(self):
        r = self.client.post("/api/notices/999999999/backfill")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "not_found")


class TestBackfillParse(unittest.TestCase):
    def test_amount_parse(self):
        from crawl.backfill import _parse_amount

        self.assertEqual(_parse_amount("12.5万元"), 125000.0)
        self.assertEqual(_parse_amount("3,000元"), 3000.0)
        self.assertEqual(_parse_amount("200万"), 2000000.0)
        self.assertIsNone(_parse_amount("面议"))


if __name__ == "__main__":
    unittest.main()
