"""桥自愈（爬虫不因桥断而停止）单测 —— 纯 mock，不碰外网/DB。

口径：桥掉线时**等它恢复**，恢复即继续采集；只有整轮等待超时才如实失败（下轮再试）。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from crawl import collector_employee as ce  # noqa: E402


class TestWaitBridgeReady(unittest.TestCase):
    def test_ready_first_attempt(self):
        state: dict = {}
        with mock.patch("wb_bridge.ensure_daemon"), \
                mock.patch("crawl.webbridge_client.ensure_bridge",
                           return_value={"bridge": True, "extensions": 1}):
            r = ce._wait_bridge_ready("jiangsu_zhaobiao", state, interval=0, ensure_wait=0)
        self.assertTrue(r["ok"])
        self.assertTrue(state["ready"])
        self.assertFalse(state.get("gave_up"))

    def test_recovers_after_retry(self):
        """第一次没起来、第二次起来 → 应继续采集（不放弃）。"""
        state: dict = {}
        seq = [{"bridge": False, "extensions": 0}, {"bridge": True, "extensions": 1}]
        with mock.patch("wb_bridge.ensure_daemon"), \
                mock.patch("crawl.webbridge_client.ensure_bridge", side_effect=seq):
            r = ce._wait_bridge_ready("jiangsu_zhaobiao", state, interval=0, ensure_wait=0)
        self.assertTrue(r["ok"])
        self.assertEqual(r["attempts"], 2)

    def test_gives_up_after_limit(self):
        state: dict = {}
        with mock.patch.object(ce, "_bridge_wait_sec", return_value=0), \
                mock.patch("wb_bridge.ensure_daemon"), \
                mock.patch("crawl.webbridge_client.ensure_bridge",
                           return_value={"bridge": False, "extensions": 0}):
            r = ce._wait_bridge_ready("jiangsu_zhaobiao", state, interval=0, ensure_wait=0)
        self.assertFalse(r["ok"])
        self.assertTrue(state["gave_up"])
        self.assertEqual(r["error"] if "error" in r else "", r.get("error", ""))  # 不抛异常即可

    def test_skips_after_gave_up(self):
        """同一轮里桥已判定不可用 → 后续 webbridge 源直接跳过，不重复等待。"""
        state = {"gave_up": True}
        r = ce._wait_bridge_ready("qianlima", state, interval=0, ensure_wait=0)
        self.assertFalse(r["ok"])
        self.assertTrue(r.get("skipped"))

    def test_run_platform_marks_failed_when_bridge_not_ready(self):
        state = {"gave_up": True}
        res = ce._run_platform("jiangsu_zhaobiao", ["绿植租摆"], 1, state)
        self.assertEqual(res["status"], "failed")
        self.assertIn("webbridge_not_ready", res["error"])
        self.assertEqual(res["notices"], [])

    def test_wait_sec_env_override(self):
        with mock.patch.dict("os.environ", {"SPIDER_BRIDGE_WAIT_SEC": "42"}):
            self.assertEqual(ce._bridge_wait_sec(), 42)
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(ce._bridge_wait_sec(), 300)


class TestOpenInChrome(unittest.TestCase):
    """铁律：开浏览器只走 Chrome，绝不用 Edge / 系统默认浏览器。"""

    def test_uses_chrome_exe(self):
        from crawl import webbridge_client as wb

        with mock.patch.object(wb, "_first_existing",
                               return_value=r"C:\Program Files\Google\Chrome\Application\chrome.exe"), \
                mock.patch("subprocess.Popen") as popen:
            exe = wb.open_in_chrome("https://example.com/")
        self.assertIn("chrome.exe", exe)
        args = popen.call_args[0][0]
        self.assertIn("chrome.exe", args[0])
        self.assertIn("https://example.com/", args)
        self.assertFalse(any("msedge" in str(a).lower() for a in args))

    def test_missing_chrome_returns_none(self):
        from crawl import webbridge_client as wb

        with mock.patch.object(wb, "_first_existing", return_value=None):
            self.assertIsNone(wb.open_in_chrome("https://example.com/"))

    def test_candidates_are_chrome_only(self):
        from crawl import webbridge_client as wb

        self.assertFalse(hasattr(wb, "EDGE_CANDIDATES"), "EDGE_CANDIDATES 死代码应已删除")
        for p in wb.CHROME_CANDIDATES:
            self.assertIn("chrome.exe", p.lower())
            self.assertNotIn("msedge", p.lower())


if __name__ == "__main__":
    unittest.main()
