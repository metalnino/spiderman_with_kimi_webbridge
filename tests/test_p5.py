"""P5 原发寻址 / 出勤简报 / 报告历史 / 任务书到期提醒 单测。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


class TestOrigin(unittest.TestCase):
    def test_origin_lines_and_url(self):
        from crawl.origin import origin_entity, origin_lines, origin_url

        text = ("…本公告发布媒介：中国政府采购网 (http://www.ccgp.gov.cn/cggg/dfgg/xxx.htm)\n"
                "信息来源：江苏省公共资源交易中心")
        lines = origin_lines(text)
        self.assertGreaterEqual(len(lines), 1)
        self.assertEqual(origin_url(text), "http://www.ccgp.gov.cn/cggg/dfgg/xxx.htm")
        self.assertEqual(origin_entity(text), "中国政府采购网")

    def test_no_origin_honest(self):
        from crawl.origin import origin_entity, origin_lines, origin_url

        self.assertEqual(origin_lines("纯招标正文没有来源行"), [])
        self.assertIsNone(origin_url("纯招标正文没有来源行"))
        self.assertIsNone(origin_entity("纯招标正文没有来源行"))

    def test_entity_map(self):
        from crawl.origin import match_entity_map, resolve_origin

        self.assertEqual(match_entity_map("招商商管北部片区南京项目群绿植租摆服务结果公告")["domain"], "dzzb.ciesco.com.cn")
        self.assertEqual(match_entity_map("华润某项目采购公告")["domain"], "szecp.crc.com.cn")
        # 标题无主体但正文来源行给单位名
        out = resolve_origin("某项目结果公告", "信息来源：华润集团守正电子招标采购平台")
        self.assertEqual(out["platform"]["domain"], "szecp.crc.com.cn")

    def test_resolve_origin_url_priority(self):
        from crawl.origin import resolve_origin

        out = resolve_origin("某项目结果公告", "发布媒介：中国政府采购网 http://www.ccgp.gov.cn/x.htm")
        self.assertEqual(out["url"], "http://www.ccgp.gov.cn/x.htm")
        self.assertEqual(out["platform"]["domain"], "www.ccgp.gov.cn")

    def test_http_fetchable(self):
        from crawl.origin import is_http_fetchable

        self.assertTrue(is_http_fetchable("http://www.ccgp.gov.cn/cggg/dfgg/x.htm"))
        self.assertTrue(is_http_fetchable("https://www.ggzy.gov.cn/information/html/a/xxx.html"))
        self.assertTrue(is_http_fetchable("http://jsggzy.jszwfw.gov.cn/jyxx/001002/x.html"))
        self.assertFalse(is_http_fetchable("https://dzzb.ciesco.com.cn/gg/xxx"))
        self.assertFalse(is_http_fetchable("https://www.chinabidding.cn/zbgs/U-xxx.html"))


class TestBriefing(unittest.TestCase):
    def _write(self, rows: list[dict]) -> Path:
        td = tempfile.mkdtemp()
        p = Path(td) / "briefing.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        return p

    def test_load_skips_bad_lines(self):
        from crawl.briefing import load

        td = tempfile.mkdtemp()
        p = Path(td) / "briefing.jsonl"
        p.write_text("not json\n" + json.dumps({"runId": "a", "platforms": ["ccgp"], "fetched": 1}) + "\n", encoding="utf-8")
        rows = load(p)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["runId"], "a")

    def test_consecutive_empty(self):
        from crawl.briefing import consecutive_empty

        rows = [
            {"platforms": ["ccgp", "chinabidding"], "fetched": 5, "empty_platforms": []},
            {"platforms": ["ccgp", "chinabidding"], "fetched": 1, "empty_platforms": []},
            {"platforms": ["ccgp", "chinabidding"], "fetched": 0, "empty_platforms": ["ccgp", "chinabidding"]},
            {"platforms": ["ccgp", "chinabidding"], "fetched": 0, "empty_platforms": ["ccgp"]},
            {"platforms": ["ccgp"], "fetched": 0, "empty_platforms": ["ccgp"]},
        ]
        out = consecutive_empty(rows, ["ccgp", "chinabidding"])
        # 最近 3 轮（r3/r4/r5）两站均零产出或未出勤 → 各 3
        self.assertEqual(out["ccgp"], 3)
        self.assertEqual(out["chinabidding"], 3)

    def test_consecutive_empty_lock(self):
        from crawl.briefing import consecutive_empty

        # briefs 为旧→新（JSONL 追加序）；最近一轮零产出、上一轮有产出 → 连续空窗=1
        rows = [
            {"platforms": ["ccgp"], "fetched": 0, "empty_platforms": ["ccgp"]},
            {"platforms": ["ccgp"], "fetched": 0, "empty_platforms": ["ccgp"]},
            {"platforms": ["ccgp"], "fetched": 1, "empty_platforms": []},
            {"platforms": ["ccgp"], "fetched": 0, "empty_platforms": ["ccgp"]},
        ]
        self.assertEqual(consecutive_empty(rows, ["ccgp"])["ccgp"], 1)

    def test_summary(self):
        from crawl.briefing import summary

        p = self._write([
            {"runId": "r1", "platforms": ["ccgp"], "fetched": 1, "open_todos": 2, "window_note": None},
        ])
        s = summary(p, ["ccgp"])
        self.assertEqual(s["runs"], 1)
        self.assertEqual(s["open_todos"], 2)
        self.assertEqual(s["last"]["runId"], "r1")


class TestWindowNote(unittest.TestCase):
    def test_note(self):
        from crawl.collector_employee import _window_note

        today = date(2026, 8, 23)
        self.assertIsNone(_window_note({"date": {"end": "2026-12-31"}}, today))
        self.assertIn("剩", _window_note({"date": {"end": "2026-08-31"}}, today))
        self.assertIn("过期", _window_note({"date": {"end": "2026-08-20"}}, today))
        self.assertIsNone(_window_note({"date": {}}, today))


class TestReportHistory(unittest.TestCase):
    def test_run_writes_history_and_briefing(self):
        from datetime import timedelta

        from crawl import collector_employee as ce

        end = (date.today() + timedelta(days=7)).isoformat()  # 动态：必然触发「剩 N 天」提醒
        with tempfile.TemporaryDirectory() as td:
            fake_report = Path(td) / "collector-report.json"
            fake_hist = Path(td) / "history"
            fake_brief = Path(td) / "briefing.jsonl"
            with mock.patch.object(ce.runner, "run_source", return_value={
                    "source_id": "ccgp", "run_id": 1, "status": "success", "error": None,
                    "raw_total": 0, "notices": [], "attempted": 0, "clean": {}, "detail": {}}), \
                 mock.patch.object(ce, "_existing_hashes", return_value=set()), \
                 mock.patch.object(ce, "_open_todo_count", return_value=0), \
                 mock.patch.object(ce, "REPORT_PATH", fake_report), \
                 mock.patch.object(ce, "REPORT_HISTORY_DIR", fake_hist), \
                 mock.patch.object(ce, "BRIEFING_PATH", fake_brief):
                res = ce.run({"keywords": ["绿植租摆"], "platforms": ["ccgp"],
                              "dateRange": {"start": "2026-07-01", "end": end}})
            self.assertGreaterEqual(res["report"]["metrics"]["elapsed_ms"], 0)
            self.assertEqual(fake_report.exists(), True)
            saved = json.loads(fake_report.read_text(encoding="utf-8"))
            self.assertIn("briefing", saved)
            self.assertIn("任务书到期提醒", saved["notes"][-1])
            hist_files = list(fake_hist.glob("*.json"))
            self.assertEqual(len(hist_files), 1)
            self.assertEqual(hist_files[0].name, saved["runId"] + ".json")
            self.assertEqual(fake_brief.exists(), True)


if __name__ == "__main__":
    unittest.main()
