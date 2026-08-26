"""员工外壳契约测试 —— collector/v1.2.0（离线；不触网不触库，用 mock 覆盖内核调用）。"""
from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from crawl import collector_employee as ce  # noqa: E402
from crawl.models import Notice  # noqa: E402

CONTRACT = json.loads((ROOT / "contract" / "collector-v1.json").read_text(encoding="utf-8"))


def fake_notice(**kw) -> Notice:
    base = dict(
        source_id="chinabidding", source_name="中国采购与招标网",
        title="某单位绿植租摆服务采购公告", detail_url="https://www.chinabidding.cn/zbgg/abc.html",
        publish_date="2026-08-08T13:10:50", city="南京", region_text="11",
        amount_text="50000 元", amount=50000.0,
    )
    base.update(kw)
    return Notice(**base)


class TestIdentity(unittest.TestCase):
    def test_implements_declared(self):
        self.assertEqual(ce.IMPLEMENTS, "collector/v1.2.0")
        self.assertEqual(ce.IDENTITY["implements"], "collector/v1.2.0")
        self.assertEqual(ce.IDENTITY["coreType"], "rule")
        self.assertEqual(ce.IDENTITY["autonomyBudget"], "deterministic")

    def test_implements_matches_contract_version(self):
        # 声明版本 = 契约 id + 契约 contractVersion
        self.assertEqual(ce.IMPLEMENTS, f'{CONTRACT["id"]}/v{CONTRACT["contractVersion"]}')


class TestInputValidation(unittest.TestCase):
    def test_valid_input_normalized(self):
        out = ce.validate_input({"keywords": ["绿植租摆", " 绿化养护 "], "platforms": ["ccgp"],
                                 "dateRange": {"start": "2026-07-01"}, "regionFilter": ["南京"]})
        self.assertEqual(out["keywords"], ["绿植租摆", "绿化养护"])
        self.assertEqual(out["platforms"], ["ccgp"])
        self.assertEqual(out["dateRange"], {"start": "2026-07-01", "end": None})
        self.assertEqual(out["regionFilter"], ["南京"])

    def test_missing_keywords_raises(self):
        with self.assertRaises(ce.ContractInputError):
            ce.validate_input({"platforms": ["ccgp"]})

    def test_bad_keywords_type_raises(self):
        with self.assertRaises(ce.ContractInputError):
            ce.validate_input({"keywords": "绿植租摆", "platforms": ["ccgp"]})
        with self.assertRaises(ce.ContractInputError):
            ce.validate_input({"keywords": [1, 2], "platforms": ["ccgp"]})

    def test_missing_platforms_raises(self):
        with self.assertRaises(ce.ContractInputError):
            ce.validate_input({"keywords": ["绿植租摆"]})

    def test_bad_date_range_raises(self):
        with self.assertRaises(ce.ContractInputError):
            ce.validate_input({"keywords": ["a"], "platforms": ["ccgp"], "dateRange": {"start": 123}})

    def test_bad_region_filter_raises(self):
        with self.assertRaises(ce.ContractInputError):
            ce.validate_input({"keywords": ["a"], "platforms": ["ccgp"], "regionFilter": "南京"})

    def test_none_falls_back_to_config_layer(self):
        out = ce.validate_input(None)
        self.assertTrue(out["keywords"])
        self.assertTrue(out["platforms"])


class TestOutputMapping(unittest.TestCase):
    def test_item_has_exact_contract_keys(self):
        item = ce.to_contract_item(fake_notice())
        self.assertEqual(list(item.keys()), list(ce.OUTPUT_KEYS))

    def test_field_values_and_types(self):
        item = ce.to_contract_item(fake_notice())
        self.assertEqual(item["title"], "某单位绿植租摆服务采购公告")
        self.assertEqual(item["platform"], "chinabidding")
        self.assertEqual(item["url"], "https://www.chinabidding.cn/zbgg/abc.html")
        self.assertEqual(item["publishTime"], "2026-08-08T13:10:50")
        self.assertEqual(item["region"], "南京")
        self.assertEqual(item["amount"], "50000 元")
        self.assertIsNone(item["summary"])
        self.assertIsNone(item["tenderFile"])
        for k in ("title", "platform", "url", "publishTime", "region", "dedupId"):
            self.assertIsInstance(item[k], str)
        for k in ("amount", "summary"):
            self.assertTrue(item[k] is None or isinstance(item[k], str), f"{k} 应为 string 或 null")
        self.assertTrue(item["tenderFile"] is None or isinstance(item["tenderFile"], dict))

    def test_dedup_id_is_md5_of_title_platform_url(self):
        n = fake_notice()
        item = ce.to_contract_item(n)
        expect = hashlib.md5((item["title"] + item["platform"] + item["url"]).encode("utf-8")).hexdigest()
        self.assertEqual(item["dedupId"], expect)
        self.assertEqual(len(item["dedupId"]), 32)

    def test_region_fallback_chain(self):
        self.assertEqual(ce.to_contract_item(fake_notice(city=None, province="江苏"))["region"], "江苏")
        self.assertEqual(ce.to_contract_item(fake_notice(city=None, province=None, region_text="11"))["region"], "11")

    def test_nullable_amount_and_summary(self):
        item = ce.to_contract_item(fake_notice(amount_text=None, amount=None))
        self.assertIsNone(item["amount"])
        self.assertIsNone(item["summary"])

    def test_publish_time_iso8601_normalization(self):
        item = ce.to_contract_item(fake_notice(publish_date="2026-07-10 09:30:00"))
        self.assertEqual(item["publishTime"], "2026-07-10T09:30:00")
        item2 = ce.to_contract_item(fake_notice(publish_date=None))
        self.assertIsNone(item2["publishTime"])  # v1.1.0：无日期 → null（不再输出空串）

    def test_detail_fills_summary_and_tenderfile(self):
        detail = {
            "ok": True,
            "error": None,
            "summary": "本项目为绿植租摆服务…",
            "tenderFile": {
                "path": "downloads/tenderfiles/ccgp/abc.pdf",
                "text": "第一章 招标公告……",
                "sourceUrl": "https://example.com/abc.pdf",
                "format": "pdf",
            },
        }
        item = ce.to_contract_item(fake_notice(), detail)
        self.assertEqual(item["summary"], "本项目为绿植租摆服务…")
        self.assertEqual(item["tenderFile"]["format"], "pdf")
        self.assertEqual(item["tenderFile"]["path"], "downloads/tenderfiles/ccgp/abc.pdf")
        # 失败详情结果：不造假，两字段均 null
        bad = ce.to_contract_item(fake_notice(), {"ok": False, "error": "no_attachment_link"})
        self.assertIsNone(bad["summary"])
        self.assertIsNone(bad["tenderFile"])

    def test_url_fallback_official(self):
        item = ce.to_contract_item(fake_notice(detail_url=None, official_url="https://x/y"))
        self.assertEqual(item["url"], "https://x/y")

    def test_dedup_items(self):
        a = ce.to_contract_item(fake_notice())
        b = ce.to_contract_item(fake_notice())
        c = ce.to_contract_item(fake_notice(title="另一条公告"))
        out = ce.dedup_items([a, b, c])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1]["title"], "另一条公告")


class TestPureFilters(unittest.TestCase):
    def test_in_date(self):
        self.assertTrue(ce._in_date("2026-08-08", {"start": "2026-07-01", "end": "2026-08-31"}))
        self.assertFalse(ce._in_date("2026-09-01", {"start": "2026-07-01", "end": "2026-08-31"}))
        self.assertTrue(ce._in_date("", {"start": "2026-07-01"}))  # 无日期不丢（内核口径）

    def test_in_region(self):
        self.assertTrue(ce._in_region("江苏 南京", ["南京", "上海"]))
        self.assertFalse(ce._in_region("泰州", ["南京", "上海"]))

    def test_blocked_count(self):
        self.assertEqual(ce.count_blocked_events([None, "", "ok"]), 0)
        self.assertEqual(ce.count_blocked_events(["HTTP 403 blocked"]), 2)
        self.assertEqual(ce.count_blocked_events(["ccgp rate_limited（连续 4 次请求均被频控）"]), 4)


class TestRunPipeline(unittest.TestCase):
    """整链路（mock 内核与 DB）：input → output + 观测报告，指标严格对齐契约。"""

    TF_OK = {
        "ok": True, "error": None, "summary": "某单位绿植租摆服务采购…",
        "tenderFile": {"path": "downloads/tenderfiles/x/a.pdf", "text": "第一章 招标公告……",
                       "sourceUrl": "https://x/a.pdf", "format": "pdf"},
    }

    @classmethod
    def setUpClass(cls):
        # 报告/历史/简报一律写临时目录，绝不污染生产 reports/（P5 修正）
        cls._td = tempfile.TemporaryDirectory()
        td = Path(cls._td.name)
        cls._patchers = [
            mock.patch.object(ce, "REPORT_PATH", td / "collector-report.json"),
            mock.patch.object(ce, "REPORT_HISTORY_DIR", td / "history"),
            mock.patch.object(ce, "BRIEFING_PATH", td / "briefing.jsonl"),
        ]
        for p in cls._patchers:
            p.start()

    @classmethod
    def tearDownClass(cls):
        for p in cls._patchers:
            p.stop()
        cls._td.cleanup()

    def _run(self, notices_per_platform, status="success", err=None, tf_results=None):
        n1 = fake_notice()
        n2 = fake_notice(title="第二条：花卉租摆项目")
        notices = {"chinabidding": [n1], "ccgp": [n2]}

        def fake_run_source(pid, **kw):
            got = notices.get(pid, []) if status != "failed" else []
            return {"source_id": pid, "run_id": 1, "status": status, "error": err,
                    "raw_total": len(got), "notices": got, "attempted": len(got),
                    "clean": {}, "detail": {}}

        # 详情/附件抓取离线化：默认全部成功；tf_results 可定制（如 [ok, fail]）
        def fake_fetch_tenderfile(pid, url):
            if tf_results:
                r = tf_results.pop(0)
                return r if r is not None else dict(self.TF_OK)
            return dict(self.TF_OK)

        with mock.patch.object(ce.runner, "run_source", side_effect=fake_run_source), \
             mock.patch.object(ce, "_existing_hashes", return_value=set()), \
             mock.patch.object(ce.tenderfile_mod, "fetch_tenderfile", side_effect=fake_fetch_tenderfile):
            return ce.run({"keywords": ["绿植租摆"], "platforms": ["chinabidding", "ccgp"],
                           "dateRange": {"start": "2026-07-01", "end": "2026-08-31"},
                           "regionFilter": ["南京", "上海", "苏州", "杭州", "武汉", "深圳", "广州", "合肥"]})

    def test_output_schema_conformance(self):
        res = self._run(None)
        for item in res["output"]:
            self.assertEqual(list(item.keys()), list(ce.OUTPUT_KEYS))
            for k in ("title", "platform", "url", "publishTime", "region", "dedupId"):
                self.assertIsInstance(item[k], str)
            self.assertTrue(item["amount"] is None or isinstance(item["amount"], str))
            self.assertTrue(item["summary"] is None or isinstance(item["summary"], str))
            self.assertTrue(item["tenderFile"] is None or isinstance(item["tenderFile"], dict))
            if item["tenderFile"]:
                for k in ("path", "text"):
                    self.assertIsInstance(item["tenderFile"][k], str)
                self.assertIn(item["tenderFile"]["format"], ("pdf", "docx", "txt"))
            self.assertEqual(item["dedupId"], hashlib.md5((item["title"] + item["platform"] + item["url"]).encode()).hexdigest())
        self.assertEqual(len(res["output"]), 2)
        self.assertEqual(res["output"][0]["platform"], "chinabidding")
        # 详情抓取成功回填
        self.assertEqual(res["output"][0]["tenderFile"]["format"], "pdf")
        self.assertEqual(res["output"][0]["summary"], "某单位绿植租摆服务采购…")

    def test_report_metrics_exactly_contract(self):
        res = self._run(None)
        m = res["report"]["metrics"]
        self.assertEqual(sorted(m.keys()), sorted(ce.METRIC_NAMES))
        # 契约 observability.metrics 的七项名字与类型
        want_types = {"fetched_count": int, "dedup_new_count": int, "platform_success_rate": dict,
                      "empty_platforms": list, "blocked_count": int, "elapsed_ms": int}
        for name, typ in want_types.items():
            self.assertIsInstance(m[name], typ, f"metric {name} 类型应为 {typ}")
        self.assertTrue(m["detail_fetch_success_rate"] is None or isinstance(m["detail_fetch_success_rate"], float))
        self.assertEqual(m["fetched_count"], 2)
        self.assertEqual(m["dedup_new_count"], 2)
        self.assertEqual(m["platform_success_rate"], {"chinabidding": 1.0, "ccgp": 1.0})
        self.assertEqual(m["empty_platforms"], [])
        self.assertEqual(m["blocked_count"], 0)
        self.assertEqual(m["detail_fetch_success_rate"], 1.0)  # 2 尝试 2 成功
        self.assertGreaterEqual(m["elapsed_ms"], 0)

    def test_detail_failures_counted_honestly(self):
        res = self._run(None, tf_results=[
            {"ok": False, "error": "detail_login_wall", "summary": None, "tenderFile": None},
            dict(self.TF_OK),
        ])
        m = res["report"]["metrics"]
        self.assertEqual(m["detail_fetch_success_rate"], 0.5)  # 1/2
        # 失败条目 tenderFile=null，不造假
        failed = [i for i in res["output"] if i["tenderFile"] is None]
        self.assertEqual(len(failed), 1)
        self.assertEqual(res["report"]["detailFetch"]["success"], 1)
        self.assertEqual(res["report"]["detailFetch"]["attempts"], 2)

    def test_failed_platform_metrics(self):
        res = self._run(None, status="failed", err="ccgp rate_limited（连续 4 次请求均被频控，冷却阶梯已耗尽）")
        m = res["report"]["metrics"]
        self.assertEqual(m["fetched_count"], 0)
        self.assertEqual(m["dedup_new_count"], 0)
        self.assertEqual(m["platform_success_rate"], {"chinabidding": 0.0, "ccgp": 0.0})
        self.assertEqual(m["empty_platforms"], ["chinabidding", "ccgp"])
        self.assertEqual(m["blocked_count"], 8)  # 每平台 4 次封禁信号
        self.assertIsNone(m["detail_fetch_success_rate"])  # 无输出条目 → 无尝试 → null

    def test_dedup_new_count_vs_existing(self):
        n1 = fake_notice()
        with mock.patch.object(ce.runner, "run_source", return_value={
                "source_id": "chinabidding", "run_id": 1, "status": "success", "error": None,
                "raw_total": 1, "notices": [n1], "attempted": 1, "clean": {}, "detail": {}}), \
             mock.patch.object(ce, "_existing_hashes", return_value={n1.content_hash()}), \
             mock.patch.object(ce.tenderfile_mod, "fetch_tenderfile", return_value=dict(self.TF_OK)):
            res = ce.run({"keywords": ["绿植租摆"], "platforms": ["chinabidding"]})
        self.assertEqual(res["report"]["metrics"]["dedup_new_count"], 0)
        self.assertEqual(res["report"]["metrics"]["fetched_count"], 1)

    def test_report_file_written(self):
        with tempfile.TemporaryDirectory() as td:
            fake_report = Path(td) / "collector-report.json"
            with mock.patch.object(ce.runner, "run_source", return_value={
                    "source_id": "ccgp", "run_id": 1, "status": "success", "error": None,
                    "raw_total": 0, "notices": [], "attempted": 0, "clean": {}, "detail": {}}), \
                 mock.patch.object(ce, "_existing_hashes", return_value=set()), \
                 mock.patch.object(ce, "REPORT_PATH", fake_report):
                res = ce.run({"keywords": ["绿植租摆"], "platforms": ["ccgp"]})
            saved = json.loads(fake_report.read_text(encoding="utf-8"))
            self.assertEqual(saved["implements"], "collector/v1.2.0")
            self.assertEqual(saved["metrics"]["fetched_count"], 0)
            self.assertIsNone(saved["metrics"]["detail_fetch_success_rate"])


class TestConfigLayer(unittest.TestCase):
    def test_config_files_exist_and_parse(self):
        kws = ce.load_keywords()
        self.assertIsInstance(kws, list)
        self.assertTrue(all(isinstance(k, str) for k in kws))
        plats = ce.load_platforms()
        self.assertIsInstance(plats, list)
        self.assertTrue(all(e.get("id") for e in plats))
        for pid, cfg in {"ccgp": None, "chinabidding": None}.items():
            self.assertTrue(any(e["id"] == pid for e in plats))
        flt = ce.load_filters()
        self.assertIn("region", flt)
        self.assertIn("budget", flt)
        self.assertIn("date", flt)

    def test_platforms_drive_kernel_sources_config(self):
        from crawl.config_loader import sources_cfg
        cfg = sources_cfg()
        # platforms.json 的 selector 参数必须生效（ccgp time_type / chinabidding list_api）
        self.assertEqual(cfg["ccgp"]["time_type"], "5")
        self.assertTrue(cfg["chinabidding"]["list_api"].startswith("https://www.chinabidding.com.cn/"))

    def test_nine_platforms_all_enabled_with_routes(self):
        plats = {e["id"]: e for e in ce.load_platforms()}
        for pid in ("ccgp", "chinabidding", "ggzy", "jsggzy", "cebpub",
                    "jiangsu_zhaobiao", "yfbzb", "qianlima", "tgnet"):
            self.assertTrue(plats[pid].get("enabled"), f"{pid} 应启用")
            self.assertIn(plats[pid].get("route"), ("http", "playwright", "webbridge"), f"{pid} route 非法")
        self.assertEqual(plats["cebpub"]["route"], "playwright")
        self.assertEqual(plats["jiangsu_zhaobiao"]["route"], "webbridge")
        self.assertEqual(plats["qianlima"]["route"], "webbridge")
        self.assertFalse(plats["rccchina"].get("enabled"))
        # route/name/proxy 属外壳层元数据，不泄漏进内核 sources_cfg 的字段本体
        from crawl.config_loader import sources_cfg
        cfg = sources_cfg()
        self.assertNotIn("route", cfg.get("cebpub") or {})

    def test_no_source_config_drift(self):
        from crawl.sources import source_config_drift, enabled_source_ids
        d = source_config_drift()
        self.assertTrue(d.get("has_platforms"), "platforms.json 应存在")
        self.assertFalse(d.get("drifted"), f"源站启用口径漂移: {d}")
        self.assertEqual(len(enabled_source_ids()), 9)

    def test_all_enabled_sources_have_backfill_route(self):
        from crawl.sources import enabled_source_ids
        from crawl import backfill as bf
        covered = set(bf.FIELD_SOURCES) | set(bf.SUMMARY_SOURCES)
        missing = set(enabled_source_ids()) - covered
        self.assertFalse(missing, f"启用源站缺详情回填路由: {missing}")

    def test_platforms_overlay_only_params(self):
        from crawl.config_loader import platform_overrides
        ov = platform_overrides()
        self.assertEqual(ov.get("cebpub"), {"search_url": "https://www.cebpubservice.com/ctpsp_iiss/searchbusinesstypebeforedooraction/getSearch.do"})


class TestPlatformRouting(unittest.TestCase):
    def test_http_platform_goes_to_kernel(self):
        with mock.patch.object(ce.runner, "run_source", return_value={"status": "success"}) as m:
            ce._run_platform("ccgp", ["绿植租摆"], 1)
            m.assert_called_once_with("ccgp", keywords=["绿植租摆"], max_pages=1)

    def test_browser_platforms_go_to_scripts(self):
        import types

        fake_mod = types.SimpleNamespace(main=lambda kws: {
            "status": "success", "error": None,
            "notices": [{"title": "x", "source_id": "cebpub", "content_hash": "h1"}],
        })
        with mock.patch.dict(ce.BROWSER_ROUTES, {"cebpub": {"route": "playwright", "module": "fake_mod"}}), \
             mock.patch.dict(sys.modules, {"fake_mod": fake_mod}):
            res = ce._run_platform("cebpub", ["绿植租摆"], 1)
        self.assertEqual(res["status"], "success")
        self.assertEqual(len(res["notices"]), 1)
        self.assertIsNone(res["raw_total"])

    def test_browser_script_exception_closes_loop(self):
        import types

        fake_mod = types.SimpleNamespace(main=lambda kws: (_ for _ in ()).throw(RuntimeError("boom")))
        with mock.patch.dict(ce.BROWSER_ROUTES, {"cebpub": {"route": "playwright", "module": "fake_mod"}}), \
             mock.patch.dict(sys.modules, {"fake_mod": fake_mod}):
            res = ce._run_platform("cebpub", ["绿植租摆"], 1)
        self.assertEqual(res["status"], "error")
        self.assertIn("boom", res["error"])

    def test_webbridge_absent_reported_honestly(self):
        import types

        fake_mod = types.SimpleNamespace(main=lambda kws: {
            "status": "failed", "error": "webbridge_not_available", "notices": [],
        })
        with mock.patch.dict(ce.BROWSER_ROUTES, {"jiangsu_zhaobiao": {"route": "webbridge", "module": "fake_mod"}}), \
             mock.patch.dict(sys.modules, {"fake_mod": fake_mod}), \
             mock.patch.object(ce, "_existing_hashes", return_value=set()), \
             mock.patch.object(ce, "REPORT_PATH", Path(tempfile.mkdtemp()) / "collector-report.json"), \
             mock.patch.object(ce, "REPORT_HISTORY_DIR", Path(tempfile.mkdtemp())), \
             mock.patch.object(ce, "BRIEFING_PATH", Path(tempfile.mkdtemp()) / "briefing.jsonl"):
            res = ce.run({"keywords": ["绿植租摆"], "platforms": ["jiangsu_zhaobiao"]})
        m = res["report"]["metrics"]
        self.assertEqual(m["fetched_count"], 0)
        self.assertEqual(m["platform_success_rate"], {"jiangsu_zhaobiao": 0.0})
        self.assertEqual(m["empty_platforms"], ["jiangsu_zhaobiao"])
        self.assertEqual(m["blocked_count"], 0)  # 桥不在线≠站点封禁，不计 blocked


class TestWebBridgeServer(unittest.TestCase):
    """本地桥服务端冒烟（随机端口，不碰真浏览器）。"""

    def test_status_endpoint(self):
        import importlib.util
        import json
        import urllib.request
        from unittest import mock

        spec = importlib.util.spec_from_file_location(
            "webbridge_server", ROOT / "scripts" / "webbridge_server.py"
        )
        mod = importlib.util.module_from_spec(spec)
        with mock.patch.dict("os.environ", {"WEBRIDGE_PORT": "0"}):
            spec.loader.exec_module(mod)
        srv = mod.Server((mod.HOST, 0), mod.Handler)
        import threading

        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            port = srv.server_address[1]
            resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["ok"])
            self.assertIn("Kimi WebBridge", data["service"])
            resp2 = urllib.request.urlopen(f"http://127.0.0.1:{port}/command", timeout=5)
            self.assertTrue(json.loads(resp2.read().decode("utf-8"))["ok"])
            # 无扩展连接时 POST /command 应返回 503 no_extension
            import urllib.error
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/command",
                data=json.dumps({"action": "list_tabs", "args": {}, "session": "t"}).encode(),
                headers={"Content-Type": "application/json"},
            )
            try:
                urllib.request.urlopen(req, timeout=5)
                self.fail("应返回 503")
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 503)
        finally:
            srv.shutdown()
            srv.server_close()


class TestEnsureBridge(unittest.TestCase):
    """一键开桥（幂等自愈）逻辑：桥在→零动作；桥不在→起服务；浏览器不在→开浏览器。"""

    def test_already_up_no_actions(self):
        from crawl import webbridge_client as wb

        with mock.patch.object(wb, "_bridge_status", return_value={"up": True, "extensions": 1}), \
             mock.patch.object(wb, "_spawn_server") as sp, \
             mock.patch.object(wb, "_open_browser_if_needed") as ob:
            res = wb.ensure_bridge()
        self.assertTrue(res["bridge"])
        self.assertEqual(res["extensions"], 1)
        self.assertEqual(res["actions"], [])
        sp.assert_not_called()
        ob.assert_not_called()

    def test_down_spawns_server_and_opens_browser(self):
        from crawl import webbridge_client as wb

        calls = {"n": 0}
        def status():
            calls["n"] += 1
            # 第一次探测 down → spawn 后 up 但扩展 0 → 开浏览器后扩展 1
            if calls["n"] == 1:
                return {"up": False, "extensions": 0}
            return {"up": True, "extensions": 0 if calls["n"] < 3 else 1}
        with mock.patch.object(wb, "_bridge_status", side_effect=status), \
             mock.patch.object(wb, "_spawn_server", return_value=True), \
             mock.patch.object(wb, "_open_browser_if_needed", return_value="C:\\fake\\chrome.exe"), \
             mock.patch.object(wb.time, "sleep"), \
             mock.patch.object(wb.time, "time", return_value=10**9):
            res = wb.ensure_bridge(wait_sec=1)
        self.assertTrue(res["bridge"])
        self.assertEqual(res["extensions"], 1)
        self.assertIn("spawn_server", res["actions"])
        self.assertTrue(any("chrome" in a for a in res["actions"]))

    def test_collector_routes_webbridge_opens_bridge_first(self):
        import types

        calls = []
        def fake_main(kws):
            calls.append(1)
            return {"status": "success", "error": None, "notices": []}
        fake_mod = types.SimpleNamespace(main=fake_main)
        with mock.patch.dict(ce.BROWSER_ROUTES, {"jiangsu_zhaobiao": {"route": "webbridge", "module": "fake_mod"}}), \
             mock.patch.dict(sys.modules, {"fake_mod": fake_mod}), \
             mock.patch("crawl.webbridge_client.ensure_bridge", return_value={"bridge": True, "extensions": 1, "actions": []}) as eb:
            res = ce._run_platform("jiangsu_zhaobiao", ["绿植租摆"], 1)
        eb.assert_called_once()
        self.assertEqual(res["status"], "success")
        self.assertEqual(calls, [1])


class TestTenderFileKernel(unittest.TestCase):
    """crawl.tenderfile 内核纯函数 + 附件抓取管线（离线，夹具自清理）。"""

    FIXTURE_HTML = """
    <html><body>
      <div id="content">某单位绿植租摆服务采购项目招标公告，预算金额 50 万元，欢迎投标。</div>
      <a href="http://static.x.com/a/login.html">登录</a>
      <a href="/oss/download?uuid=abc123&filesource=zbwj">招标文件.pdf</a>
      <a href="https://x.com/files/附件二：报价表.docx">附件二：报价表.docx</a>
      <a href="https://x.com/logo.png">logo</a>
      <a href="https://x.com/d/ann.txt">补充说明.txt</a>
    </body></html>
    """

    def test_discover_attachment_urls(self):
        from crawl import tenderfile as tf

        found = tf.discover_attachment_urls(self.FIXTURE_HTML, "https://www.ccgp.gov.cn/cggg/dfgg/x.html")
        urls = [u for u, _ in found]
        self.assertEqual(len(found), 3)  # pdf/docx/txt；png/login 排除
        self.assertIn("https://www.ccgp.gov.cn/oss/download?uuid=abc123&filesource=zbwj", urls)
        self.assertIn("https://x.com/files/附件二：报价表.docx", urls)
        # pdf 优先排序
        self.assertEqual([f for _, f in found], ["pdf", "docx", "txt"])

    def test_discover_none(self):
        from crawl import tenderfile as tf

        self.assertEqual(tf.discover_attachment_urls("<html><a href='/login'>登录</a></html>", "https://x.com/"), [])

    def test_extract_docx_text(self):
        from crawl import tenderfile as tf

        doc_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>第一章 招标公告</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>预算金额：50万元</w:t></w:r></w:p></w:body></w:document>"
        )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", doc_xml)
        buf.seek(0)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.docx"
            p.write_bytes(buf.read())
            text = tf.extract_docx_text(p)
        self.assertIn("第一章 招标公告", text)
        self.assertIn("预算金额：50万元", text)

    def test_extract_pdf_text(self):
        from crawl import tenderfile as tf

        import fitz

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.pdf"
            doc = fitz.open()
            page = doc.new_page()
            # 默认 helv 字体不含 CJK 字形，夹具用 ASCII（被测对象是提取管线本身）
            page.insert_text((72, 72), "TenderDoc-LVZHI-2026 body text")
            doc.save(str(p))
            doc.close()
            text = tf.extract_pdf_text(p)
        self.assertIn("TenderDoc-LVZHI-2026", text)

    def test_clean_extracted_text(self):
        from crawl import tenderfile as tf

        junk = "Þÿ`Å³Á¢" * 30
        good = "第一章 招标公告\n第二章 投标人须知"
        self.assertNotIn("Þÿ", tf.clean_extracted_text(junk + "\n" + good))
        self.assertIn("第一章 招标公告", tf.clean_extracted_text(junk + "\n" + good))

    def test_fetch_tenderfile_no_attachment_honest(self):
        from crawl import tenderfile as tf

        body = "某单位绿植租摆服务采购项目招标公告。" * 30  # > 200 字符，绕过空页判定

        class FakeHttp:
            def get_text(self, url, headers=None):
                return f"<html><body>{body}</body></html>"

        res = tf.fetch_tenderfile("ccgp", "https://www.ccgp.gov.cn/x.html", http=FakeHttp())
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "no_attachment_link")
        self.assertIsNone(res["tenderFile"])
        self.assertIn("某单位绿植租摆", res["summary"])

    def test_fetch_tenderfile_bad_url_honest(self):
        from crawl import tenderfile as tf

        res = tf.fetch_tenderfile("ccgp", "")
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "no_detail_url")
        self.assertIsNone(res["tenderFile"])

    def test_magic_mismatch_rejects_html_as_pdf(self):
        from crawl import tenderfile as tf

        self.assertFalse(tf._is_pdf_magic(b"<html>login page</html>" * 20))
        self.assertTrue(tf._is_pdf_magic(b"%PDF-1.7\n" + b"x" * 500))
        self.assertFalse(tf._is_zip_magic(b"<html>x</html>"))
        self.assertTrue(tf._is_zip_magic(b"PK\x03\x04" + b"y" * 500))


class TestTenderFileModes(unittest.TestCase):
    """详情抓取路由：ggzy b 页 HTTP / WebBridge / cebpub vaptcha 阻塞（全离线）。"""

    def test_ggzy_detail_page_url(self):
        from crawl import tenderfile as tf

        a = "https://www.ggzy.gov.cn/information/deal/html/a/0067/0101/20260724/00676585f1c7c6084cae90d1987a8b2414d4.html"
        self.assertEqual(
            tf.ggzy_detail_page_url(a),
            "https://www.ggzy.gov.cn/information/deal/html/b/0067/0101/20260724/00676585f1c7c6084cae90d1987a8b2414d4.html",
        )
        self.assertEqual(tf.ggzy_detail_page_url("https://www.ggzy.gov.cn/information/deal/html/b/x/y/1.html"),
                         "https://www.ggzy.gov.cn/information/deal/html/b/x/y/1.html")
        self.assertIsNone(tf.ggzy_detail_page_url("https://other.example.com/x.html"))

    def test_cebpub_vaptcha_gate_registers_todo(self):
        from crawl import tenderfile as tf

        shell = {"text": "首页|联系我们 ×", "links": [], "cookie": "", "session": "s1"}
        with mock.patch.object(tf, "_bridge_page", return_value=dict(shell)), \
             mock.patch("crawl.captcha_queue.open_todo") as todo:
            res = tf.fetch_tenderfile("cebpub", "https://ctbpsp.com/#/bulletinDetail?uuid=x")
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "detail_vaptcha_gated")
        self.assertIsNone(res["tenderFile"])
        self.assertTrue(todo.called)  # vaptcha 人工验证登记待办，绝不绕过

    def test_cebpub_des_decrypt(self):
        from crawl import tenderfile as tf

        from Crypto.Cipher import DES

        import base64

        key = tf.CEBPUB_DES_KEY
        plain = '{"success":true,"data":"https://file.example.com/a.pdf"}'.encode()
        pad = 8 - len(plain) % 8
        plain += bytes([pad]) * pad
        enc = DES.new(key, DES.MODE_ECB).encrypt(plain)
        self.assertEqual(
            tf.cebpub_des_decrypt(base64.b64encode(enc).decode()),
            '{"success":true,"data":"https://file.example.com/a.pdf"}',
        )

    def test_cebpub_bridge_attachment_after_vaptcha(self):
        from crawl import tenderfile as tf

        import fitz

        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "t.pdf"
            doc = fitz.open()
            pg = doc.new_page()
            pg.insert_text((72, 72), "Cebpub bulletin attachment 2026")
            doc.save(str(pdf))
            doc.close()
            pdf_bytes = pdf.read_bytes()

        rendered = {"text": "某项目招标公告 正文内容 一、招标条件 本项目已具备招标条件，现进行公开招标。" * 6,
                    "links": [{"t": "下载", "h": "https://file.cebpubservice.com/x.pdf", "on": ""}],
                    "cookie": "", "session": "s1"}

        class FakeFailHttp:
            def request(self, url, headers=None, **kw):
                raise RuntimeError("offline in test")

        with mock.patch.object(tf, "_bridge_page", return_value=dict(rendered)), \
             mock.patch.object(tf, "HttpSession", return_value=FakeFailHttp()), \
             mock.patch.object(tf, "_bridge_download_b64", return_value=(pdf_bytes, "")), \
             mock.patch.object(tf, "time", mock.MagicMock()):
            res = tf.fetch_tenderfile("cebpub", "https://ctbpsp.com/#/bulletinDetail?uuid=y")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["tenderFile"]["format"], "pdf")
        self.assertIn("Cebpub bulletin attachment", res["tenderFile"]["text"])
        Path(ROOT / res["tenderFile"]["path"]).unlink(missing_ok=True)

    def _fake_http(self, page_html="", attachment_bytes=b""):
        calls = []

        class FakeHttp:
            def get_text(self, url, headers=None):
                calls.append(("text", url))
                return page_html

            def request(self, url, headers=None, **kw):
                calls.append(("raw", url))
                return 200, attachment_bytes, url

        return FakeHttp(), calls

    def test_fetch_ggzy_http_full_pipeline(self):
        from crawl import tenderfile as tf

        import fitz

        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "t.pdf"
            doc = fitz.open()
            page = doc.new_page()
            page.insert_text((72, 72), "GGZY TenderDoc body text 2026")
            doc.save(str(pdf))
            doc.close()
            pdf_bytes = pdf.read_bytes()

        b_html = (
            "<html><body><h4>某单位绿植租摆服务招标公告</h4><p>一、招标条件 本项目资金来源为自筹资金，"
            "现进行公开招标。二、项目概况 预算 50 万元，采购绿植租摆及绿化养护服务，服务期一年，"
            "投标人须具备独立法人资格，本项目不接受联合体投标，开标时间另行通知，详见招标文件。</p>"
            '<a href="/oss/download?uuid=abc&filesource=1">招标文件.pdf</a></body></html>'
        )
        fake_http, calls = self._fake_http(b_html, pdf_bytes)
        a_url = "https://www.ggzy.gov.cn/information/deal/html/a/0067/0101/20260724/00676585f1c7c6084cae90d1987a8b2414d4.html"
        res = tf.fetch_tenderfile("ggzy", a_url, http=fake_http)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["tenderFile"]["format"], "pdf")
        self.assertIn("GGZY TenderDoc", res["tenderFile"]["text"])
        self.assertIn("/html/b/", calls[0][1])  # 抓的是 b 页
        # 夹具自清理
        Path(ROOT / res["tenderFile"]["path"]).unlink(missing_ok=True)

    def test_fetch_ggzy_http_no_attachment_honest_summary(self):
        from crawl import tenderfile as tf

        b_html = "<html><body><p>" + ("某公告正文，无附件。" * 30) + "</p></body></html>"
        fake_http, _ = self._fake_http(b_html)
        res = tf.fetch_tenderfile("ggzy", "https://www.ggzy.gov.cn/information/deal/html/a/1/2/20260724/x.html", http=fake_http)
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "no_attachment_link")
        self.assertIsNone(res["tenderFile"])
        self.assertIn("某公告正文", res["summary"])

    def test_fetch_via_bridge_member_wall_honest(self):
        from crawl import tenderfile as tf

        page = {"text": "绿化租摆和园区除草 发布日期：2026-08-18 招标编号：【正式会员“登录”后可浏览】 正文摘要……" * 5,
                "links": [], "cookie": "", "session": "s1"}
        with mock.patch("crawl.webbridge_client.ensure_bridge", return_value={"bridge": True, "extensions": 1}), \
             mock.patch("crawl.webbridge_client.navigate", return_value={"ok": True}), \
             mock.patch("crawl.webbridge_client.evaluate", return_value={"ok": True, "data": {"value": json.dumps(page, ensure_ascii=False)}}), \
             mock.patch("crawl.webbridge_client.export_document_cookie", return_value={"ok": True, "cookie": ""}), \
             mock.patch("db.load_env", return_value={"JIANGSU_ZHAOBIAO_USER": "u1", "JIANGSU_ZHAOBIAO_PASS": "p1"}), \
             mock.patch.object(tf, "_jiangsu_bridge_login_ocr", return_value="captcha_wrong_loop"), \
             mock.patch.object(tf, "ensure_jiangsu_login", return_value="need_human_captcha"), \
             mock.patch.object(tf, "time", mock.MagicMock()):
            res = tf.fetch_detail_via_bridge("jiangsu_zhaobiao", "https://jiangsu.zhaobiao.cn/bidding_v_x.html")
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "detail_login_need_human_captcha")
        self.assertIsNone(res["tenderFile"])
        self.assertIn("绿化租摆", res["summary"])

    def test_jiangsu_login_ok_then_member_download(self):
        from crawl import tenderfile as tf

        import fitz

        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "t.pdf"
            doc = fitz.open()
            pg = doc.new_page()
            pg.insert_text((72, 72), "Jiangsu member TenderDoc 2026")
            doc.save(str(pdf))
            doc.close()
            pdf_bytes = pdf.read_bytes()

        gated = {"text": "绿化租摆项目 招标编号：【正式会员“登录”后可浏览】" * 4,
                 "links": [], "cookie": "", "session": "s1"}
        member = {"text": "绿化租摆项目 招标编号：ZB2026-001 招标文件下载 第一章 招标公告 预算 50 万元" * 4,
                  "links": [{"t": "招标文件下载", "h": "https://jiangsu.zhaobiao.cn/down_abc.pdf"}],
                  "cookie": "", "session": "s2"}

        calls = {"n": 0}

        def fake_page(sid, url):
            calls["n"] += 1
            return dict(gated) if calls["n"] == 1 else dict(member)

        class FakeFailHttp:  # HTTP 优先路径失败 → 验证浏览器内下载兜底路径
            def request(self, url, headers=None, **kw):
                raise RuntimeError("offline in test")

        with mock.patch.object(tf, "_bridge_page", side_effect=fake_page), \
             mock.patch("db.load_env", return_value={"JIANGSU_ZHAOBIAO_USER": "u1", "JIANGSU_ZHAOBIAO_PASS": "p1"}), \
             mock.patch.object(tf, "_jiangsu_bridge_login_ocr", return_value="ok"), \
             mock.patch.object(tf, "HttpSession", return_value=FakeFailHttp()), \
             mock.patch.object(tf, "_bridge_download_b64", return_value=(pdf_bytes, "")), \
             mock.patch.object(tf, "time", mock.MagicMock()):
            res = tf.fetch_detail_via_bridge("jiangsu_zhaobiao", "https://jiangsu.zhaobiao.cn/bidding_v_x.html")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["tenderFile"]["format"], "pdf")
        self.assertIn("Jiangsu member TenderDoc", res["tenderFile"]["text"])
        Path(ROOT / res["tenderFile"]["path"]).unlink(missing_ok=True)

    def test_ensure_jiangsu_login_captcha_registers_todo(self):
        from crawl import tenderfile as tf

        with mock.patch.object(tf, "_jiangsu_login_http", return_value="login_failed"), \
             mock.patch.object(tf, "_jiangsu_bridge_login_ocr", return_value="captcha_wrong_loop"), \
             mock.patch("db.load_env", return_value={"JIANGSU_ZHAOBIAO_USER": "u1", "JIANGSU_ZHAOBIAO_PASS": "p1"}), \
             mock.patch("crawl.webbridge_client.ensure_bridge", return_value={"bridge": True, "extensions": 1}), \
             mock.patch("crawl.webbridge_client.navigate", return_value={"ok": True}), \
             mock.patch("crawl.webbridge_client.evaluate", return_value={"ok": True, "data": {"value": json.dumps(
                 {"captcha_box": True, "captcha_rendered": True, "has_quit": False, "still_login": True})}}), \
             mock.patch("crawl.captcha_queue.open_todo") as todo, \
             mock.patch.object(tf, "time", mock.MagicMock()):
            state = tf.ensure_jiangsu_login()
        self.assertEqual(state, "need_human_captcha")
        self.assertTrue(todo.called)  # 登记人工待办，绝不自动绕过滑块

    def test_fetch_via_bridge_attachment_download(self):
        from crawl import tenderfile as tf

        import fitz

        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "t.pdf"
            doc = fitz.open()
            pg = doc.new_page()
            pg.insert_text((72, 72), "Bridge TenderDoc body 2026")
            doc.save(str(pdf))
            doc.close()
            pdf_bytes = pdf.read_bytes()

        page = {"text": "某项目招标公告 正文……" * 30,
                "links": [{"t": "招标文件", "h": "https://file.example.com/tender.pdf"}], "cookie": "sid=1",
                "session": "s1"}

        class FakeHttp:
            def request(self, url, headers=None, **kw):
                self.last_headers = headers
                return 200, pdf_bytes, url

        fake_http = FakeHttp()
        with mock.patch("crawl.webbridge_client.ensure_bridge", return_value={"bridge": True, "extensions": 1}), \
             mock.patch("crawl.webbridge_client.navigate", return_value={"ok": True}), \
             mock.patch("crawl.webbridge_client.evaluate", return_value={"ok": True, "data": {"value": json.dumps(page, ensure_ascii=False)}}), \
             mock.patch("crawl.webbridge_client.export_document_cookie", return_value={"ok": True, "cookie": "sid=1"}), \
             mock.patch.object(tf, "_bridge_download_b64", return_value=(None, "in-browser disabled in test")), \
             mock.patch.object(tf, "HttpSession", return_value=fake_http), \
             mock.patch.object(tf, "time", mock.MagicMock()):
            res = tf.fetch_detail_via_bridge("chinabidding", "https://www.chinabidding.cn/zbgg/x.html")
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["tenderFile"]["format"], "pdf")
        self.assertIn("Bridge TenderDoc", res["tenderFile"]["text"])
        self.assertIn("sid=1", fake_http.last_headers.get("Cookie", ""))
        Path(ROOT / res["tenderFile"]["path"]).unlink(missing_ok=True)


class TestCaptchaOcr(unittest.TestCase):
    """数字验证码识别：确定性算法自测（渲染数字回读）+ AI API 路径 + HTTP 登录流。"""

    def _render_digits(self, digits: str) -> bytes:
        import io

        from PIL import Image, ImageDraw, ImageFont

        font = ImageFont.truetype("arial.ttf", 32)
        img = Image.new("RGB", (150, 50), "white")
        d = ImageDraw.Draw(img)
        d.text((10, 6), digits, fill="black", font=font)
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()

    def test_ocr_deterministic_reads_rendered_digits(self):
        from crawl import captcha_ocr

        for digits in ("4829", "0315", "7760"):
            got = captcha_ocr.ocr_deterministic(self._render_digits(digits))
            self.assertEqual(got, digits, f"识别 {digits} → {got}")

    def test_ocr_via_api_parses_content(self):
        from crawl import captcha_ocr

        cfg = {"enabled": True, "endpoint": "https://api.example.com/v1/chat/completions",
               "api_key": "sk-test", "model": "vision"}
        resp = {"choices": [{"message": {"content": "验证码数字是 4829。"}}]}

        class FakeResp:
            def read(self):
                return json.dumps(resp).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", return_value=FakeResp()):
            self.assertEqual(captcha_ocr.ocr_via_api(b"fake-image", cfg), "4829")

    def test_ocr_via_api_disabled_returns_none(self):
        from crawl import captcha_ocr

        self.assertIsNone(captcha_ocr.ocr_via_api(b"x", {"enabled": False}))
        self.assertIsNone(captcha_ocr.ocr_via_api(b"x", {"enabled": True, "api_key": ""}))

    def _fake_http_login(self, post_bodies):
        """登录流 FakeHttp：页→验证码→POST；POST 按 post_bodies 依次返回。"""
        page_html = (
            '<html><form><input type="hidden" name="loginType" value="0">'
            '<input type="hidden" name="x1" value="v1">'
            '<input name="loginUserId"><input name="loginPassword">'
            '<input class="yzm" name="yzm" id="yzm"><img id="randimg" src="/common/img.jsp?n=l&1">'
            "</form></html>"
        )

        class C:
            def __init__(self, name, value):
                self.name, self.value = name, value

        class FakeHttp:
            def __init__(self):
                self.cj = [C("JSESSIONID", "abc123")]
                self.calls = []

            def request(self, url, **kw):
                self.calls.append(url)
                if "login.html" in url:
                    return 200, page_html.encode("gbk"), url
                if "img.jsp" in url:
                    return 200, b"jpeg-bytes-fake" * 80, url
                if "homePageUc.do" in url:
                    return 200, "会员中心 账户管理".encode("gbk"), url
                if "loginPost" in url:
                    body = kw.get("data") or b""
                    post_bodies.append(body.decode())
                    return 200, b"ok", url
                return 200, b"", url

        return FakeHttp()

    def test_jiangsu_login_http_flow(self):
        from crawl import tenderfile as tf

        bodies = []
        fake_http = self._fake_http_login(bodies)
        with mock.patch("db.load_env", return_value={"JIANGSU_ZHAOBIAO_USER": "u1", "JIANGSU_ZHAOBIAO_PASS": "p1"}), \
             mock.patch.object(tf, "HttpSession", return_value=fake_http), \
             mock.patch("crawl.captcha_ocr.ocr_captcha", return_value="4829"), \
             mock.patch("crawl.cookie_store.save_cookie_header") as save, \
             mock.patch.object(tf.time, "sleep", mock.MagicMock()):
            state = tf._jiangsu_login_http()
        self.assertEqual(state, "ok")
        self.assertEqual(len(bodies), 1)
        self.assertIn("loginUserId=u1", bodies[0])
        self.assertIn("yzm=4829", bodies[0])
        self.assertIn("loginType=userId", bodies[0])  # 账号流 loginType 必须 userId（非 mobile/0）
        self.assertTrue(save.called)  # 登录 Cookie 落盘（HTTP 详情/附件复用）

    def test_jiangsu_login_http_captcha_retry(self):
        from crawl import tenderfile as tf

        bodies = []
        fake_http = self._fake_http_login(bodies)
        ocr_calls = []

        def fake_ocr(img):
            ocr_calls.append(1)
            return "1111" if len(ocr_calls) == 1 else "4829"

        def fake_post(url, **kw):
            if "loginPost" in url:
                body = kw.get("data") or b""
                bodies.append(body.decode())
                if b"yzm=1111" in body:
                    return 200, "验证码错误，请重新输入".encode("gbk"), url
                return 200, b"ok", url
            if "homePageUc.do" in url:
                return 200, "会员中心 账户管理".encode("gbk"), url
            if "login.html" in url:
                return 200, ("<html><form><input type='hidden' name='loginType' value='0'>"
                             "<input name='loginUserId'><input name='loginPassword'>"
                             "<input class='yzm' name='yzm'><img id='randimg' src='/common/img.jsp?n=l&1'>"
                             "</form></html>").encode("gbk"), url
            return 200, b"jpeg-bytes" * 60, url

        fake_http.request = fake_post
        with mock.patch("db.load_env", return_value={"JIANGSU_ZHAOBIAO_USER": "u1", "JIANGSU_ZHAOBIAO_PASS": "p1"}), \
             mock.patch.object(tf, "HttpSession", return_value=fake_http), \
             mock.patch("crawl.captcha_ocr.ocr_captcha", side_effect=fake_ocr), \
             mock.patch("crawl.cookie_store.save_cookie_header"), \
             mock.patch.object(tf.time, "sleep", mock.MagicMock()):
            state = tf._jiangsu_login_http()
        self.assertEqual(state, "ok")
        self.assertEqual(len(bodies), 2)  # 验证码错误后换图重试成功

    def test_jiangsu_login_http_captcha_case_variant_retry(self):
        """AI 读到混合大小写（eTly）→ 同图大小写变体重试成功（服务端认小写）。"""
        from crawl import tenderfile as tf

        bodies = []

        class C:
            def __init__(self, name, value):
                self.name, self.value = name, value

        class FakeHttp:
            def __init__(self):
                self.cj = [C("JSESSIONID", "abc")]

            def request(self, url, **kw):
                if "loginPost" in url:
                    body = (kw.get("data") or b"").decode()
                    bodies.append(body)
                    if "yzm=eTly" in body:
                        return 200, "验证码错误，请重新输入".encode("gbk"), url
                    if "yzm=etly" in body:
                        return 200, b"ok", url
                    return 200, "验证码错误".encode("gbk"), url
                if "homePageUc.do" in url:
                    return 200, "会员中心 账户管理".encode("gbk"), url
                if "login.html" in url:
                    return 200, ("<html><form><input type='hidden' name='loginType' value='0'>"
                                 "<input name='loginUserId'><input name='loginPassword'>"
                                 "<input class='yzm' name='yzm'><img id='randimg' src='/common/img.jsp?n=l&1'>"
                                 "</form></html>").encode("gbk"), url
                return 200, b"jpeg-bytes" * 60, url

        fake_http = FakeHttp()
        with mock.patch("db.load_env", return_value={"JIANGSU_ZHAOBIAO_USER": "u1", "JIANGSU_ZHAOBIAO_PASS": "p1"}), \
             mock.patch.object(tf, "HttpSession", return_value=fake_http), \
             mock.patch("crawl.captcha_ocr.ocr_captcha", return_value="eTly"), \
             mock.patch("crawl.cookie_store.save_cookie_header"), \
             mock.patch.object(tf.time, "sleep", mock.MagicMock()):
            state = tf._jiangsu_login_http()
        self.assertEqual(state, "ok")
        self.assertEqual(len(bodies), 2)  # 同图两 POST：原读 eTly → 小写变体 etly 成功
        self.assertIn("yzm=etly", bodies[1])

    def test_ensure_login_prefers_http_then_bridge(self):
        from crawl import tenderfile as tf

        # OCR 已配置（AI 多模态可用）→ HTTP 验证码登录优先
        with mock.patch("crawl.captcha_ocr.load_ocr_cfg", return_value={"enabled": True}), \
             mock.patch.object(tf, "_jiangsu_login_http", return_value="ok"):
            self.assertEqual(tf.ensure_jiangsu_login(), "ok")
        # OCR 未配置 → 跳过 HTTP；桥内 OCR 登录失败 → 滑块人工兜底
        with mock.patch("crawl.captcha_ocr.load_ocr_cfg", return_value={"enabled": False}), \
             mock.patch.object(tf, "_jiangsu_login_http", return_value="ok") as http_login, \
             mock.patch.object(tf, "_jiangsu_bridge_login_ocr", return_value="captcha_wrong_loop") as bridge_ocr, \
             mock.patch("db.load_env", return_value={"JIANGSU_ZHAOBIAO_USER": "u1", "JIANGSU_ZHAOBIAO_PASS": "p1"}), \
             mock.patch("crawl.webbridge_client.ensure_bridge", return_value={"bridge": True, "extensions": 1}), \
             mock.patch("crawl.webbridge_client.navigate", return_value={"ok": True}), \
             mock.patch("crawl.webbridge_client.evaluate", return_value={"ok": True, "data": {"value": json.dumps(
                 {"captcha_box": True, "has_quit": False, "still_login": True})}}), \
             mock.patch("crawl.captcha_queue.open_todo"), \
             mock.patch.object(tf, "time", mock.MagicMock()):
            self.assertEqual(tf.ensure_jiangsu_login(), "need_human_captcha")
            http_login.assert_not_called()  # 未启用 AI OCR 时不空耗 HTTP 验证码尝试
            bridge_ocr.assert_called_once()

    def test_jiangsu_bridge_login_ocr_flow(self):
        """桥内 AI OCR 登录：取图→OCR→提交→登录态验证，全自动无人工。"""
        from crawl import tenderfile as tf

        import base64

        b64 = base64.b64encode(b"fake-captcha-image").decode()
        seq = [
            # 1) 初始登录态检查：未登录
            {"ok": True, "data": {"value": json.dumps({"has_quit": False, "has_phone_mask": False})}},
            # 2) 取验证码
            {"ok": True, "data": {"value": json.dumps({"ok": True, "b64": b64})}},
            # 3) 提交
            {"ok": True, "data": {"value": json.dumps({"ok": True})}},
            # 4) 提交后状态：已登录
            {"ok": True, "data": {"value": json.dumps({"has_quit": True, "has_phone_mask": True})}},
        ]
        with mock.patch("crawl.webbridge_client.ensure_bridge", return_value={"bridge": True, "extensions": 1}), \
             mock.patch("crawl.webbridge_client.navigate", return_value={"ok": True}), \
             mock.patch("crawl.webbridge_client.evaluate", side_effect=seq), \
             mock.patch("crawl.captcha_ocr.ocr_captcha", return_value="4829") as ocr, \
             mock.patch.object(tf, "time", mock.MagicMock()):
            state = tf._jiangsu_bridge_login_ocr("u1", "p1")
        self.assertEqual(state, "ok")
        ocr.assert_called_once_with(b"fake-captcha-image")


if __name__ == "__main__":
    unittest.main(verbosity=2)
