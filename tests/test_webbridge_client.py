"""webbridge_client 扩展函数单元测试（全离线，mock call）。"""
from __future__ import annotations

import unittest
from unittest import mock


class TestExportCookies(unittest.TestCase):
    def test_cdp_full_cookie_header(self):
        from crawl import webbridge_client as wb

        resp = {
            "ok": True,
            "data": {
                "cookies": [
                    {"name": "a", "value": "1", "httpOnly": False},
                    {"name": "SESSION", "value": "secret", "httpOnly": True},
                ]
            },
        }
        with mock.patch("crawl.webbridge_client.call", return_value=resp) as c:
            out = wb.export_cookies("https://bid.rccchina.com/", session="s")
        self.assertTrue(out["ok"])
        self.assertEqual(out["cookie"], "a=1; SESSION=secret")
        c.assert_called_once()
        args = c.call_args
        self.assertEqual(args[0][0], "cdp")
        self.assertEqual(args[0][1]["method"], "Network.getCookies")
        self.assertEqual(args[0][1]["params"]["urls"], ["https://bid.rccchina.com/"])

    def test_cdp_error_honest(self):
        from crawl import webbridge_client as wb

        with mock.patch("crawl.webbridge_client.call", return_value={"ok": False, "error": {"code": "x"}}):
            out = wb.export_cookies("https://bid.rccchina.com/", session="s")
        self.assertFalse(out["ok"])
        self.assertEqual(out["cookie"], "")
        self.assertEqual(out["cookies"], [])

    def test_data_may_be_json_string(self):
        from crawl import webbridge_client as wb

        import json

        payload = {"cookies": [{"name": "k", "value": "v", "httpOnly": True}]}
        resp = {"ok": True, "data": json.dumps(payload)}
        with mock.patch("crawl.webbridge_client.call", return_value=resp):
            out = wb.export_cookies("https://bid.rccchina.com/", session="s")
        self.assertTrue(out["ok"])
        self.assertEqual(out["cookie"], "k=v")


if __name__ == "__main__":
    unittest.main(verbosity=2)
