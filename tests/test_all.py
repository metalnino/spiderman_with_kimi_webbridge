"""Stdlib unittest suite (pytest unavailable due to pip/ssl)."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# 真实外网抓取测试：默认跳过，设 SPIDER_LIVE_TESTS=1 才跑（避免站点抖动打挂套件）
LIVE = os.environ.get("SPIDER_LIVE_TESTS") == "1"


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


class TestP3(unittest.TestCase):
    def test_jsggzy_registered(self):
        from crawl.sources import REGISTRY, get_source

        self.assertIn("jsggzy", REGISTRY)
        src = get_source("jsggzy")
        self.assertEqual(src.source_id, "jsggzy")

    def test_jiangsu_zhaobiao_registered(self):
        from crawl.sources import REGISTRY, get_source

        self.assertIn("jiangsu_zhaobiao", REGISTRY)
        src = get_source("jiangsu_zhaobiao")
        self.assertEqual(src.source_id, "jiangsu_zhaobiao")

    @unittest.skipUnless(LIVE, "live network test (set SPIDER_LIVE_TESTS=1)")
    def test_jiangsu_zhaobiao_fetch_sample(self):
        from crawl.sources.jiangsu_zhaobiao import JiangsuZhaobiaoSource

        src = JiangsuZhaobiaoSource()
        items = list(src.fetch(["绿化养护"], max_pages=1))
        self.assertGreater(len(items), 0)
        self.assertTrue(all(i.source_id == "jiangsu_zhaobiao" for i in items[:5]))
        self.assertTrue(any("bidding_v_" in (i.detail_url or "") or "_v_" in (i.detail_url or "") for i in items[:10]))

    @unittest.skipUnless(LIVE, "live network test (set SPIDER_LIVE_TESTS=1)")
    def test_chinabidding_detail_without_cookie(self):
        from crawl.sources.chinabidding_detail import cookie_from_env, fetch_detail_fields

        # 无 cookie 时行为可预期：不抛异常；login_wall 多为 True
        self.assertTrue(cookie_from_env() is None or isinstance(cookie_from_env(), str))
        # 使用公开列表页 URL 做降级探测可能 404；用站点首页验证函数可调用
        out = fetch_detail_fields("https://www.chinabidding.cn/")
        self.assertIn("has_cookie", out)
        self.assertIn("login_wall", out)

    @unittest.skipUnless(LIVE, "live network test (set SPIDER_LIVE_TESTS=1)")
    def test_jsggzy_fetch_sample(self):
        from crawl.sources.jsggzy import JsggzySource

        src = JsggzySource()
        items = list(src.fetch(["绿化养护"], max_pages=1))
        self.assertGreater(len(items), 0)
        self.assertTrue(all(i.province == "江苏" or "江苏" in (i.region_text or "") for i in items[:5]))

    def test_crm_build(self):
        sys.path.insert(0, str(ROOT / "scripts" / "jobs"))
        import build_crm_db

        build_crm_db.main()
        self.assertTrue((ROOT / "data" / "web" / "crm.html").exists())


class TestLedgerAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        from crawl.api import app

        cls.client = TestClient(app)

    def test_health(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_meta_sources_pruned(self):
        r = self.client.get("/api/meta")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("province_city", body)
        # 只保留 4 站；ggzy/jsggzy 已停用
        self.assertNotIn("ggzy", body["sources"])
        self.assertNotIn("jsggzy", body["sources"])
        self.assertEqual(len(body["sources"]), 4)

    def test_notices_limit(self):
        r = self.client.get("/api/notices", params={"limit": "5"})
        self.assertEqual(r.status_code, 200)
        self.assertLessEqual(len(r.json()["items"]), 5)

    def test_readonly_post_rejected(self):
        self.assertEqual(self.client.post("/api/health").status_code, 405)
        self.assertEqual(self.client.put("/api/summary").status_code, 405)

    def test_captcha_post_bad_id(self):
        r = self.client.post("/api/captcha/open", json={"id": 0})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])

    def test_index_serves_shell(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("绿植招采运营台", r.text)


class TestCaptchaFlow(unittest.TestCase):
    def test_cookie_store_roundtrip(self):
        from crawl import cookie_store

        p = cookie_store.save_cookie_header("unittest_src", "a=1; b=2", meta={"t": 1})
        self.assertTrue(p.exists())
        self.assertEqual(cookie_store.cookie_header("unittest_src"), "a=1; b=2")
        st = cookie_store.status("unittest_src")
        self.assertTrue(st["has_cookie"])
        p.unlink(missing_ok=True)

    def test_open_and_resolve_with_paste(self):
        from crawl.captcha_flow import open_for_human, resolve_todo
        from crawl.captcha_queue import open_todo
        from crawl import cookie_store

        tid = open_todo("cebpub", "https://example.com/captcha-test", "单元测试待办", "ut")
        with mock.patch("crawl.captcha_flow.webbridge_client.available", return_value=False), mock.patch(
            "crawl.captcha_flow.webbrowser.open", return_value=True
        ) as wb:
            out = open_for_human(tid)
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("fallback_browser"))
        wb.assert_called()
        done = resolve_todo(tid, cookie_header="sid=abc; path=/")
        self.assertTrue(done.get("ok"))
        self.assertTrue(done.get("cookie_saved"))
        self.assertEqual(cookie_store.cookie_header("cebpub"), "sid=abc; path=/")
        cookie_store.path_for("cebpub").unlink(missing_ok=True)


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


class TestDetail(unittest.TestCase):
    def test_parse_ccgp_detail(self):
        from crawl.detail import parse_ccgp_detail

        html = (
            "<html><body>"
            "<div>项目编号：330703260040030000035-YG2026-FW8350-ZFCG017-5</div>"
            "<div>采购单位 金华市金东区机关物业管理中心</div>"
            "<div>代理机构名称 浙江金华阳光招标代理有限公司</div>"
            "<div>总中标金额 ￥33.146000 万元（人民币）</div>"
            "</body></html>"
        )
        d = parse_ccgp_detail(html)
        self.assertEqual(d.get("project_code"), "330703260040030000035-YG2026-FW8350-ZFCG017-5")
        self.assertEqual(d.get("buyer"), "金华市金东区机关物业管理中心")
        self.assertEqual(d.get("agency"), "浙江金华阳光招标代理有限公司")
        self.assertAlmostEqual(d.get("amount"), 331460.0, places=0)
        self.assertIn("33.146000 万元", d.get("amount_text") or "")


class TestEntry(unittest.TestCase):
    def test_run_incremental_entry_imports(self):
        """主增量入口 import 链必须可用（曾因 build_incremental_html 拼错而崩）。"""
        spec = importlib.util.spec_from_file_location(
            "run_incremental", str(ROOT / "scripts" / "jobs" / "run_incremental.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(callable(mod.main))


if __name__ == "__main__":
    unittest.main()
