"""中标企业确定性抽取单测（纯函数，不碰外网/DB）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crawl import winner_extract as we  # noqa: E402


class TestExtractWinnerFromText(unittest.TestCase):
    def test_basic_label(self):
        self.assertEqual(we.extract_winner_from_text("中标供应商：南京景天园林有限公司"), "南京景天园林有限公司")

    def test_label_with_name_suffix(self):
        self.assertEqual(we.extract_winner_from_text("中标供应商名称：某绿化工程有限公司"), "某绿化工程有限公司")

    def test_bracket_annotations_removed(self):
        self.assertEqual(
            we.extract_winner_from_text("中标（成交）供应商：南京景天园林有限公司（综合评分第一）"),
            "南京景天园林有限公司",
        )
        self.assertEqual(
            we.extract_winner_from_text("成交供应商：某园林公司（地址：南京市玄武区）"),
            "某园林公司",
        )

    def test_amount_noise_truncated(self):
        # 名字后紧跟金额/评分等噪声标签要截断
        w = we.extract_winner_from_text("中标人：南京景天园林有限公司 中标金额：12.5万元")
        self.assertEqual(w, "南京景天园林有限公司")

    def test_first_of_multiple(self):
        self.assertEqual(
            we.extract_winner_from_text("中标供应商：A园林有限公司、B花卉有限公司"),
            "A园林有限公司",
        )

    def test_negative_no_winner(self):
        self.assertIsNone(we.extract_winner_from_text("中标供应商：无"))
        self.assertIsNone(we.extract_winner_from_text("本项目因投标不足三家，流标。"))
        self.assertIsNone(we.extract_winner_from_text("废标：无有效投标人。"))

    def test_no_label_returns_none(self):
        self.assertIsNone(we.extract_winner_from_text("中标金额：100万元"))
        self.assertIsNone(we.extract_winner_from_text(""))

    def test_noise_not_entity(self):
        self.assertIsNone(we.extract_winner_from_text("中标供应商：123456"))
        self.assertIsNone(we.extract_winner_from_text("中标供应商：详见附件"))


class TestExtractWinnerFromNotice(unittest.TestCase):
    def test_not_result_stage(self):
        r = we.extract_winner_from_notice({"notice_stage": "bidding", "summary": "中标供应商：某公司"})
        self.assertEqual(r["status"], "not_result")
        self.assertIsNone(r["winner"])

    def test_result_extracted_from_summary(self):
        r = we.extract_winner_from_notice(
            {"notice_stage": "result", "summary": "成交供应商名称：某园林工程有限公司"}
        )
        self.assertEqual(r["status"], "extracted")
        self.assertEqual(r["winner"], "某园林工程有限公司")
        self.assertEqual(r["source"], "summary")

    def test_result_unknown_when_no_extractable(self):
        r = we.extract_winner_from_notice({"notice_stage": "result", "summary": "如需查看详细内容，请先免费注册"})
        self.assertEqual(r["status"], "unknown")
        self.assertIsNone(r["winner"])

    def test_result_fallback_to_title(self):
        r = we.extract_winner_from_notice({"notice_stage": "result", "title": "某项目中标人：某园林工程有限公司"})
        self.assertEqual(r["status"], "extracted")
        self.assertEqual(r["winner"], "某园林工程有限公司")


class TestIsPlausibleEntity(unittest.TestCase):
    def test_plausible(self):
        self.assertTrue(we.is_plausible_entity("南京景天园林有限公司"))
        self.assertTrue(we.is_plausible_entity("某绿化中心"))
        self.assertTrue(we.is_plausible_entity("南京市某委员会"))

    def test_implausible(self):
        self.assertFalse(we.is_plausible_entity(None))
        self.assertFalse(we.is_plausible_entity("无"))
        self.assertFalse(we.is_plausible_entity(""))
        self.assertFalse(we.is_plausible_entity("12345"))


if __name__ == "__main__":
    unittest.main()
