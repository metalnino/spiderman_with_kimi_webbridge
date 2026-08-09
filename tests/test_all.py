"""Stdlib unittest suite (pytest unavailable due to pip/ssl)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


class TestClean(unittest.TestCase):
    def test_positive_pass(self):
        from crawl.pipeline.clean import clean_title

        self.assertEqual(clean_title("某单位绿植租摆服务采购公告").decision, "pass")

    def test_negative_or_no_stem(self):
        from crawl.pipeline.clean import clean_title

        self.assertEqual(clean_title("办公家具采购项目").decision, "drop")

    def test_manual(self):
        from crawl.pipeline.clean import clean_notice

        self.assertEqual(clean_notice("绿植租摆", "irrelevant").decision, "drop")
        self.assertEqual(clean_notice("无关", "relevant").decision, "pass")


class TestFilters(unittest.TestCase):
    def test_cascade(self):
        from crawl.filters import cities_for_province, reset_city_when_province_changes, source_capability_hint

        self.assertIn("南京", cities_for_province("江苏"))
        self.assertIsNone(reset_city_when_province_changes("江苏", "浙江", "南京"))
        self.assertIn("登录", source_capability_hint("chinabidding") or "")

    def test_apply(self):
        from crawl.filters import apply_filters

        rows = [
            {"source_id": "ggzy", "city": "南京", "title": "绿植", "clean_status": "pass", "manual_label": None},
            {"source_id": "chinabidding", "city": "杭州", "title": "绿植", "clean_status": "pass", "manual_label": "irrelevant"},
        ]
        self.assertEqual(len(apply_filters(rows, source_ids=["ggzy"])), 1)
        self.assertEqual(len(apply_filters(rows, exclude_irrelevant=True)), 1)


class TestAIHooks(unittest.TestCase):
    def test_off_and_degrade(self):
        from crawl import ai_hooks

        with mock.patch.object(ai_hooks, "load_ai_cfg", return_value={"enabled": False}):
            self.assertEqual(ai_hooks.classify_relevance("绿植租摆项目").decision, "pass")
        with mock.patch.object(ai_hooks, "load_ai_cfg", return_value={"enabled": True, "endpoint": "fail://x"}):
            self.assertEqual(ai_hooks.classify_relevance("绿植租摆项目").decision, "pass")
            self.assertEqual(ai_hooks.expand_keywords("绿植"), ["绿植"])
            self.assertIsNone(ai_hooks.extract_buyer("x"))

    def test_default_file(self):
        from crawl.ai_hooks import load_ai_cfg

        self.assertFalse(load_ai_cfg().get("enabled"))


class TestModels(unittest.TestCase):
    def test_hash(self):
        from crawl.models import Notice

        a = Notice(source_id="ggzy", source_name="x", title="A", external_id="id1")
        b = Notice(source_id="ggzy", source_name="x", title="B", external_id="id1")
        self.assertEqual(a.content_hash(), b.content_hash())
        row = Notice(source_id="ccgp", source_name="y", title="绿植租摆").to_row()
        self.assertEqual(len(row["content_hash"]), 40)


class TestScheduler(unittest.TestCase):
    def test_state(self):
        from crawl import scheduler

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.json"
            with mock.patch.object(scheduler, "STATE", p):
                scheduler.save_state({"runs": [{"returncode": 0}]})
                self.assertEqual(scheduler.load_state()["runs"][0]["returncode"], 0)


class TestWarm(unittest.TestCase):
    def test_warm_ccgp_flag(self):
        from crawl.warm_session import should_warm, warm_source

        self.assertTrue(should_warm("ccgp"))
        r = warm_source("ggzy")
        self.assertIn("warmed", r)


class TestDBOps(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from db import ping

        info = ping()
        if not info.get("ok"):
            raise unittest.SkipTest("db unavailable")
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "migrate_ops.py")], cwd=str(ROOT))
        if r.returncode != 0:
            raise unittest.SkipTest("migrate failed")

    def test_keywords(self):
        from crawl.keywords import enabled_keywords, seed_keywords_from_config, set_keyword_enabled

        seed_keywords_from_config()
        set_keyword_enabled("绿植租摆", False)
        self.assertNotIn("绿植租摆", enabled_keywords(fallback_trial=False))
        set_keyword_enabled("绿植租摆", True)
        self.assertIn("绿植租摆", enabled_keywords(fallback_trial=False))

    def test_captcha(self):
        from crawl.captcha_queue import close_todo, list_open, open_todo

        tid = open_todo("cebpub", "https://example.com/u", "待办", "t")
        self.assertTrue(any(x["id"] == tid for x in list_open()))
        self.assertTrue(close_todo(tid))
        self.assertTrue(all(x["id"] != tid for x in list_open()))

    def test_clean_manual(self):
        from crawl.db_store import upsert_notices
        from crawl.models import Notice
        from crawl.pipeline.apply_clean import refresh_clean_status, set_manual_label
        from db import connect

        upsert_notices(
            [
                Notice(
                    source_id="ggzy",
                    source_name="测试",
                    title="单元测试绿植租摆项目",
                    external_id="pytest-clean-1",
                )
            ]
        )
        refresh_clean_status(limit=50)
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM notices WHERE external_id=%s", ("pytest-clean-1",))
                nid = cur.fetchone()["id"]
        finally:
            conn.close()
        set_manual_label(nid, "irrelevant")
        conn = connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT clean_status, manual_label FROM notices WHERE id=%s", (nid,))
                row = cur.fetchone()
                self.assertEqual(row["manual_label"], "irrelevant")
                self.assertEqual(row["clean_status"], "drop")
        finally:
            conn.close()

    def test_dashboard(self):
        from crawl.dashboard import build_dashboard
        from crawl.keywords import seed_keywords_from_config

        seed_keywords_from_config()
        text = build_dashboard().read_text(encoding="utf-8")
        self.assertIn("运行监控", text)
        self.assertIn("线索工作台", text)
        self.assertIn("验证码待办", text)


if __name__ == "__main__":
    unittest.main()
