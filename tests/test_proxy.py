"""代理配置解析 + qianlima 路由切换（全离线，不发起真实请求）。"""
from __future__ import annotations

import importlib
import unittest
from unittest import mock

from crawl.config_loader import proxy_for


class TestProxyResolution(unittest.TestCase):
    def test_no_config_no_env(self):
        with mock.patch("crawl.config_loader.proxy_cfg", return_value={}), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(proxy_for("qianlima"))

    def test_per_source_wins_over_default(self):
        cfg = {"default": "http://a:1", "per_source": {"qianlima": "http://b:2"}}
        with mock.patch("crawl.config_loader.proxy_cfg", return_value=cfg), \
             mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(proxy_for("qianlima"), "http://b:2")
            self.assertEqual(proxy_for("ccgp"), "http://a:1")

    def test_env_wins_over_all(self):
        cfg = {"default": "http://a:1", "per_source": {"qianlima": "http://b:2"}}
        with mock.patch("crawl.config_loader.proxy_cfg", return_value=cfg), \
             mock.patch.dict("os.environ", {"SPIDER_PROXY": "http://c:3"}):
            self.assertEqual(proxy_for("qianlima"), "http://c:3")

    def test_invalid_scheme_raises(self):
        with mock.patch("crawl.config_loader.proxy_cfg", return_value={"default": "socks5://x:1"}), \
             mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                proxy_for("qianlima")


class TestHttpSessionProxy(unittest.TestCase):
    def test_opener_has_proxy_handler_when_configured(self):
        import urllib.request

        from crawl.http_session import HttpSession

        with mock.patch("crawl.http_session.proxy_for", return_value="http://127.0.0.1:7890"):
            s = HttpSession("qianlima")
        self.assertEqual(s.proxy, "http://127.0.0.1:7890")
        handlers = [h for h in s.opener.handlers if isinstance(h, urllib.request.ProxyHandler)]
        self.assertEqual(len(handlers), 1)
        self.assertEqual(handlers[0].proxies, {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"})

    def test_no_proxy_handler_when_direct(self):
        import urllib.request

        from crawl.http_session import HttpSession

        with mock.patch("crawl.http_session.proxy_for", return_value=None):
            s = HttpSession("qianlima")
        self.assertIsNone(s.proxy)
        # urllib build_opener 默认自带一个 ProxyHandler；直连时不注入显式代理，
        # 其内容跟随系统代理设置（本机可能配了系统代理），不做内容断言。
        handlers = [h for h in s.opener.handlers if isinstance(h, urllib.request.ProxyHandler)]
        self.assertEqual(len(handlers), 1)
        self.assertNotEqual(handlers[0].proxies.get("http"), "http://127.0.0.1:7890")


class TestQianlimaRouteSwitch(unittest.TestCase):
    def test_proxy_configured_uses_http_runner(self):
        from crawl import collector_employee as ce

        with mock.patch("crawl.collector_employee.proxy_for", return_value="http://127.0.0.1:7890"), \
             mock.patch.object(ce.runner, "run_source", return_value={
                 "source_id": "qianlima", "status": "success", "notices": [], "raw_total": 0,
             }) as rs:
            res = ce._run_platform("qianlima", ["绿植租摆"], 1)
        rs.assert_called_once_with("qianlima", keywords=["绿植租摆"], max_pages=1)
        self.assertEqual(res["status"], "success")

    def test_no_proxy_uses_webbridge_route(self):
        from crawl import collector_employee as ce

        fake_mod = mock.MagicMock()
        fake_mod.main.return_value = {"status": "success", "error": None, "notices": []}
        with mock.patch("crawl.collector_employee.proxy_for", return_value=None), \
             mock.patch.object(importlib, "import_module", return_value=fake_mod) as im, \
             mock.patch.object(ce.runner, "run_source") as rs:
            res = ce._run_platform("qianlima", ["绿植租摆"], 1)
        rs.assert_not_called()
        im.assert_called_once_with("crawl_qianlima_wb")
        self.assertEqual(res["status"], "success")


if __name__ == "__main__":
    unittest.main()
