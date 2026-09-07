"""原发转爬路由单测（纯函数，不碰外网/DB）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crawl.origin import fetch_route_for, is_http_fetchable  # noqa: E402


class TestFetchRouteFor(unittest.TestCase):
    def test_ccgp_central(self):
        self.assertEqual(fetch_route_for("https://www.ccgp.gov.cn/xxx"), "ccgp_http")
        self.assertEqual(fetch_route_for("http://www.ccgp.gov.cn"), "ccgp_http")

    def test_ccgp_regional(self):
        # 各省市政府采购网与中央同平台同结构
        self.assertEqual(fetch_route_for("http://www.ccgp-jiangsu.gov.cn/"), "ccgp_http")
        self.assertEqual(fetch_route_for("https://www.ccgp-shanghai.gov.cn/x"), "ccgp_http")

    def test_ggzy(self):
        self.assertEqual(fetch_route_for("https://www.ggzy.gov.cn/information/xxx"), "ggzy_http")

    def test_jszwfw(self):
        self.assertEqual(fetch_route_for("http://jsggzy.jszwfw.gov.cn/xxx"), "ggzy_http")

    def test_unknown(self):
        self.assertIsNone(fetch_route_for("https://dzzb.ciesco.com.cn/"))
        self.assertIsNone(fetch_route_for("https://example.com/ccgp"))
        self.assertIsNone(fetch_route_for(""))
        self.assertIsNone(fetch_route_for(None))


class TestIsHttpFetchable(unittest.TestCase):
    def test_wrapper(self):
        self.assertTrue(is_http_fetchable("https://www.ccgp.gov.cn/x"))
        self.assertTrue(is_http_fetchable("http://www.ccgp-jiangsu.gov.cn/"))
        self.assertFalse(is_http_fetchable("https://dzzb.ciesco.com.cn/"))
        self.assertFalse(is_http_fetchable(""))


if __name__ == "__main__":
    unittest.main()
