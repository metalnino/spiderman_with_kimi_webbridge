"""P7 召回自证：水位游标 + ccgp 翻页/已见边界 单测（不碰外网/DB）。"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


class TestWatermark(unittest.TestCase):
    def test_merge_and_cap(self):
        from crawl import watermark

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(watermark, "WATERMARK_DIR", Path(td)):
                new, total = watermark.merge("ccgp", ["a", "b", "a", "c"])
                self.assertEqual((new, total), (3, 3))
                new2, total2 = watermark.merge("ccgp", ["a", "d"])
                self.assertEqual((new2, total2), (1, 4))
                self.assertEqual(watermark.load("ccgp"), {"a", "b", "c", "d"})
                # 空轮：不丢数据
                n3, t3 = watermark.merge("ccgp", [])
                self.assertEqual((n3, t3), (0, 4))
                watermark.reset("ccgp")
                self.assertEqual(watermark.load("ccgp"), set())

    def test_cap_drops_oldest(self):
        from crawl import watermark

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(watermark, "WATERMARK_DIR", Path(td)), \
                 mock.patch.object(watermark, "MAX_IDS_PER_SOURCE", 3):
                watermark.merge("s", ["1", "2", "3"])
                watermark.merge("s", ["4", "5"])
                self.assertEqual(watermark.load("s"), {"3", "4", "5"})


def _mk_html(items):
    blocks = "".join(
        f'<li><a href="https://www.ccgp.gov.cn/cggg/dfgg/t202608{i:02d}_123.htm">{t}</a>'
        f'<span>2026.08.{i:02d} 10:00:00</span><span>采购人：某单位 | 代理机构：某代理 | 公开招标公告 | 南京 |</span></li>'
        for i, t in items
    )
    return f"<html><ul>{blocks}</ul></html>"


class TestCcgpWatermarkBoundary(unittest.TestCase):
    def test_stops_at_seen_page(self):
        from crawl import watermark
        from crawl.sources.ccgp import CcgpSource

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(watermark, "WATERMARK_DIR", Path(td)):
                # 预置水位：旧公告A 已见；旧公告B 新见
                watermark.merge("ccgp", ["20260801"])
                src = CcgpSource()
                pages = {
                    "page_index=1": _mk_html([(1, "旧公告A"), (2, "旧公告B")]),
                    "page_index=2": _mk_html([(3, "更旧公告C"), (4, "更旧公告D")]),
                }
                # 第 2 页两 id 也全部进水位（模拟上一轮已扫到第 2 页）
                watermark.merge("ccgp", ["20260803", "20260804"])
                watermark.set_last_pages("ccgp", 3)  # 历史曾扫得更深 → 边界可信

                def fake_get_text(url, headers=None):
                    for k, v in pages.items():
                        if k in url:
                            return v
                    return "<html></html>"

                with mock.patch.object(src.http, "get_text", side_effect=fake_get_text), \
                     mock.patch.object(src.http, "sleep", return_value=None):
                    notices = list(src.fetch(["绿植租摆"], max_pages=1))
                # 第 1 页含新 id（旧B）→ 继续；第 2 页整页已见且历史更深 → 停
                self.assertEqual(src.last_scanned_pages, 2)
                self.assertEqual(len(notices), 4)
                ids = {n.external_id for n in notices}
                self.assertIn("20260802", ids)
                self.assertIn("20260803", ids)

    def test_cold_start_scans_past_seen_page(self):
        # 冷启动保护：水位只来自第 1 页（last_scan_pages=0）→ 第 1 页全见也不停，翻到空/上限
        from crawl import watermark
        from crawl.sources.ccgp import CcgpSource

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(watermark, "WATERMARK_DIR", Path(td)):
                watermark.merge("ccgp", ["20260801", "20260802"])
                src = CcgpSource()
                pages = {
                    "page_index=1": _mk_html([(1, "旧公告A"), (2, "旧公告B")]),
                    "page_index=2": _mk_html([(3, "更深公告C")]),
                    "page_index=3": _mk_html([(4, "更深公告D")]),
                }

                def fake_get_text(url, headers=None):
                    for k, v in pages.items():
                        if k in url:
                            return v
                    return "<html></html>"

                with mock.patch.object(src.http, "get_text", side_effect=fake_get_text), \
                     mock.patch.object(src.http, "sleep", return_value=None), \
                     mock.patch.dict("os.environ", {"SPIDER_CCGP_MAX_PAGES": "3"}):
                    list(src.fetch(["绿植租摆"], max_pages=1))
                self.assertEqual(src.last_scanned_pages, 3)  # 冷启动不提前停

    def test_no_watermark_scans_cap(self):
        from crawl import watermark
        from crawl.sources.ccgp import CcgpSource

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(watermark, "WATERMARK_DIR", Path(td)), \
                 mock.patch.dict("os.environ", {"SPIDER_CCGP_MAX_PAGES": "3"}):
                src = CcgpSource()

                def fake_get_text(url, headers=None):
                    n = int(url.split("page_index=")[1].split("&")[0])
                    return _mk_html([(n, f"第{n}页公告")])

                with mock.patch.object(src.http, "get_text", side_effect=fake_get_text), \
                     mock.patch.object(src.http, "sleep", return_value=None):
                    list(src.fetch(["绿植租摆"], max_pages=1))
                self.assertEqual(src.last_scanned_pages, 3)


class TestCcgpAgencyParse(unittest.TestCase):
    def test_agency_from_list(self):
        from crawl.sources.ccgp import CcgpSource

        html = ('<li><a href="https://www.ccgp.gov.cn/cggg/dfgg/t20260801_123.htm">某绿植租摆项目招标公告</a>'
                '<span>2026.08.01 10:00:00</span><span>采购人：某医院 | 代理机构：某招标代理有限公司 | 公开招标公告 | 南京 |</span></li>')
        items = CcgpSource()._parse(f"<ul>{html}</ul>", "绿植租摆")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].buyer, "某医院")
        self.assertEqual(items[0].agency, "某招标代理有限公司")


class TestGgzyWatermarkBoundary(unittest.TestCase):
    def _rec(self, rid, title):
        return {"id": rid, "title": title, "publishTime": "2026-08-01 10:00:00",
                "url": "/information/html/a/1/2/3/x.html", "province": "320000",
                "provinceText": "江苏省", "cityText": "南京"}

    def test_stops_at_seen_page_and_reports_pages(self):
        from crawl import watermark
        from crawl.sources.ggzy import GgzySource

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(watermark, "WATERMARK_DIR", Path(td)):
                watermark.merge("ggzy", ["1", "2"])
                watermark.set_last_pages("ggzy", 2)  # 历史曾扫得更深 → 边界可信
                src = GgzySource()
                pages = {
                    1: {"code": 200, "data": {"records": [self._rec("1", "旧公告一"), self._rec("2", "旧公告二")]}},
                    2: {"code": 200, "data": {"records": [self._rec("3", "更旧公告三")]}},
                }

                def fake_json(url, data=None, headers=None):
                    page = int(str(data).split("PAGENUMBER=")[1].split("&")[0])
                    return pages.get(page, {"code": 200, "data": {"records": []}})

                with mock.patch.object(src.http, "get_json", side_effect=fake_json), \
                     mock.patch.object(src.http, "sleep", return_value=None):
                    notices = list(src.fetch(["绿植租摆"], max_pages=1))
                # 第 1 页整页已见 → 停（第 2 页不扫）
                self.assertEqual(src.last_scanned_pages, 1)
                self.assertEqual(len(notices), 2)

    def test_no_watermark_scans_cap(self):
        from crawl import watermark
        from crawl.sources.ggzy import GgzySource

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(watermark, "WATERMARK_DIR", Path(td)), \
                 mock.patch.dict("os.environ", {"SPIDER_GGZY_MAX_PAGES": "2"}):
                src = GgzySource()

                def fake_json(url, data=None, headers=None):
                    page = int(str(data).split("PAGENUMBER=")[1].split("&")[0])
                    return {"code": 200, "data": {"records": [self._rec(f"p{page}", f"第{page}页公告")]}}

                with mock.patch.object(src.http, "get_json", side_effect=fake_json), \
                     mock.patch.object(src.http, "sleep", return_value=None):
                    list(src.fetch(["绿植租摆"], max_pages=1))
                self.assertEqual(src.last_scanned_pages, 2)


class TestCcgpBackfillJob(unittest.TestCase):
    """回溯作业离线验证：多页全窗口扫描 + 空页/水位边界停（不碰网络/DB）。"""

    def _load_job(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "backfill_ccgp_window", ROOT / "scripts" / "jobs" / "backfill_ccgp_window.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _mk(self, rid, city="南京", pub="2026-07-10 10:00:00"):
        from crawl.models import Notice

        return Notice(source_id="ccgp", source_name="中国政府采购网", external_id=rid,
                      title=f"绿植租摆项目{rid}", publish_date=pub, city=city,
                      detail_url=f"https://www.ccgp.gov.cn/cggg/dfgg/t{rid}_1.htm")

    class FakeSource:
        def __init__(self, pages):
            self.pages = pages
            self.calls = 0

        def _fetch_page(self, url, collected):
            self.calls += 1
            return "html"

        def _parse(self, html, kw):
            return list(self.pages[min(self.calls, len(self.pages)) - 1])

    def test_scan_pages_until_empty(self):
        from crawl import watermark

        job = self._load_job()
        p1 = [self._mk("20260701"), self._mk("20260702", city="北京")]
        p2 = [self._mk("20260703")]
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(watermark, "WATERMARK_DIR", Path(td)), \
                 mock.patch.object(job, "CcgpSource", lambda: self.FakeSource([p1, p2, []])), \
                 mock.patch.object(job, "upsert_notices", return_value={"attempted": 0, "affected": 0}):
                rc = job.main(["--max-pages", "5"])
        self.assertEqual(rc, 0)  # 空页即停，不炸

    def test_boundary_stops_before_older_pages(self):
        from crawl import watermark

        job = self._load_job()
        p1 = [self._mk("20260701"), self._mk("20260702", city="北京")]
        p2 = [self._mk("20260703")]
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(watermark, "WATERMARK_DIR", Path(td)):
                watermark.merge("ccgp", ["20260701", "20260702"])  # 第 1 页整页已见
                watermark.set_last_pages("ccgp", 2)  # 历史曾扫得更深 → 边界可信
                fake = self.FakeSource([p1, p2, []])
                with mock.patch.object(job, "CcgpSource", lambda: fake), \
                     mock.patch.object(job, "upsert_notices", return_value={"attempted": 0, "affected": 0}):
                    rc = job.main(["--max-pages", "5"])
        self.assertEqual(rc, 0)
        self.assertEqual(fake.calls, 1)  # 第 2 页（更旧）不扫

    def test_fetch_failure_exit1(self):
        job = self._load_job()

        class Boom:
            def _fetch_page(self, url, collected):
                raise RuntimeError("ccgp rate_limited")

            def _parse(self, html, kw):
                return []

        with mock.patch.object(job, "CcgpSource", Boom):
            rc = job.main(["--max-pages", "3"])
        self.assertEqual(rc, 1)


class TestAutoBackfillPass(unittest.TestCase):
    def test_selects_actionable_missing_amount_only(self):
        from crawl import backfill as bf

        items = [
            {"platform": "ccgp", "title": "某招标公告", "url": "u1", "amount": None, "dedupId": "d1", "notice_stage": "bidding"},
            {"platform": "ccgp", "title": "某结果公告", "url": "u2", "amount": None, "dedupId": "d2", "notice_stage": "result"},
            {"platform": "ccgp", "title": "已有金额公告", "url": "u3", "amount": 100.0, "dedupId": "d3", "notice_stage": "bidding"},
            {"platform": "chinabidding", "title": "非HTTP源", "url": "u4", "amount": None, "dedupId": "d4", "notice_stage": "bidding"},
        ]
        with mock.patch.object(bf, "find_notice_id_by_item", return_value=7), \
             mock.patch.object(bf, "backfill_notice", return_value={"ok": True, "fields": {"amount": 5000.0}}):
            stats = bf.auto_backfill_pass(items, ["ccgp", "chinabidding"], per_source_limit=5)
        self.assertEqual(stats["attempted"], 1)  # 仅 bidding 且缺金额的 ccgp 条目
        self.assertEqual(stats["filled"], 1)
        self.assertEqual(items[0]["amount"], 5000.0)

    def test_env_off(self):
        from crawl import backfill as bf

        with mock.patch.dict("os.environ", {"SPIDER_NO_AUTO_BACKFILL": "1"}):
            self.assertEqual(bf.auto_backfill_pass([], ["ccgp"])["enabled"], False)


if __name__ == "__main__":
    unittest.main()
