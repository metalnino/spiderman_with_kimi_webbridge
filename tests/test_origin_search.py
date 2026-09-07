"""原发站站内检索 + ggzy b-page 字段提取单测（纯函数 + mock，不碰外网）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from crawl import origin_search as os_mod  # noqa: E402
from crawl.tenderfile import _extract_ggzy_origin_and_fields  # noqa: E402


class TestSearchKeyword(unittest.TestCase):
    def test_strips_stage_words(self):
        kw = os_mod.search_keyword("南京某医院绿植租摆服务采购项目中标结果公告")
        self.assertNotIn("中标", kw)
        self.assertNotIn("结果公告", kw)
        self.assertIn("南京某医院", kw)
        self.assertLessEqual(len(kw), 20)

    def test_empty_title(self):
        self.assertEqual(os_mod.search_keyword(""), "")


class TestMatchGgzy(unittest.TestCase):
    def test_match(self):
        results = [
            {"title": "南京某医院绿植租摆服务采购项目结果公告", "url": "https://www.ggzy.gov.cn/x"},
            {"title": "另一项目绿化养护", "url": "https://www.ggzy.gov.cn/y"},
        ]
        m = os_mod.match_ggzy("南京某医院绿植租摆服务采购项目中标结果公告", results)
        self.assertIsNotNone(m)
        self.assertEqual(m["url"], "https://www.ggzy.gov.cn/x")

    def test_no_match(self):
        results = [{"title": "完全不同的另一项目", "url": "https://www.ggzy.gov.cn/y"}]
        self.assertIsNone(os_mod.match_ggzy("南京某医院绿植租摆服务采购项目", results))


class TestExtractGgzyFields(unittest.TestCase):
    # 与真实 ggzy b-page 结构一致：字段用「;」分隔
    HTML = """<html><body>
      <div>信息来源：<label id="platformName">上海</label></div>
      <div>项目编号：CG2026SHA015471;项目名称：办公室绿植租摆服务;交易机构：上海农村产权交易所有限公司;成交价格：1.2996万元;中标供应商：上海某园林绿化有限公司</div>
    </body></html>"""

    def test_extract_fields(self):
        out = _extract_ggzy_origin_and_fields(self.HTML)
        self.assertEqual(out["source"], "上海")
        self.assertEqual(out["fields"]["project_code"], "CG2026SHA015471")
        self.assertEqual(out["fields"]["buyer"], "上海农村产权交易所有限公司")
        self.assertEqual(out["fields"]["amount_text"], "1.2996万元")
        self.assertEqual(out["fields"]["winner"], "上海某园林绿化有限公司")


class TestEnrichFromGgzy(unittest.TestCase):
    def test_enrich_flow(self):
        from crawl import backfill as bf

        with mock.patch.object(bf, "_load_row", return_value={"id": 1, "title": "某医院绿植租摆中标结果公告", "source_id": "chinabidding"}), \
                mock.patch.object(bf.origin_search, "search_keyword", return_value="某医院绿植租摆"), \
                mock.patch.object(bf.origin_search, "search_ggzy", return_value=[{"title": "某医院绿植租摆结果公告", "url": "https://www.ggzy.gov.cn/b"}]), \
                mock.patch.object(bf.origin_search, "match_ggzy", return_value={"title": "某医院绿植租摆结果公告", "url": "https://www.ggzy.gov.cn/b"}), \
                mock.patch.object(bf, "fetch_tenderfile", return_value={"ok": True, "fields": {"buyer": "某医院", "amount_text": "12.5万元"}, "origin": {"source": "上海"}}), \
                mock.patch.object(bf, "update_notice_detail") as upd, \
                mock.patch.object(bf, "_save_result") as save:
            r = bf.enrich_from_ggzy(7)
        self.assertTrue(r["ok"])
        self.assertEqual(r["url"], "https://www.ggzy.gov.cn/b")
        upd.assert_called_once_with(7, {"buyer": "某医院", "amount_text": "12.5万元"})
        self.assertTrue(save.called)

    def test_no_match_honest(self):
        from crawl import backfill as bf

        with mock.patch.object(bf, "_load_row", return_value={"id": 1, "title": "某项目", "source_id": "chinabidding"}), \
                mock.patch.object(bf.origin_search, "search_keyword", return_value="某项目"), \
                mock.patch.object(bf.origin_search, "search_ggzy", return_value=[]), \
                mock.patch.object(bf.origin_search, "match_ggzy", return_value=None):
            r = bf.enrich_from_ggzy(7)
        self.assertFalse(r["ok"])
        self.assertEqual(r["error"], "no_ggzy_match")


if __name__ == "__main__":
    unittest.main()
