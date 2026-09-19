"""WebBridge 标签卫生 + 浏览器源过滤口径 单测 —— 全离线，不碰真桥/外网/DB。

回归目标（用户 2026-09-19 报「Chrome 里 tab 越堆越多、吃内存」）：
  详情抓取按条开会话（`tf-<站>-<hash>`），而 `list_tabs` 是**按会话隔离**的，
  原实现只在 collector 的 `_enrich_tenderfiles` 结束时关一次，新增的详情补全阶段根本没调它
  ⇒ 实测每轮遗留约 40 个 tab（22:00 轮日志里只有 jiangsu 自己那句 closed 1 tabs）。
另外锁住：tgnet 原先**完全没有**城市/发布时间过滤（385 条里 340 条越窗、319 条不在 8 城）。
"""
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


class TestCloseSession(unittest.TestCase):
    def test_uses_extension_action(self):
        from crawl import webbridge_client as wb

        with mock.patch.object(wb, "call", return_value={"ok": True, "data": {"success": True, "closed": 3}}) as c:
            self.assertEqual(wb.close_session("s1"), 3)
        self.assertEqual(c.call_args[0][0], "close_session")

    def test_falls_back_to_per_tab(self):
        from crawl import webbridge_client as wb

        with mock.patch.object(wb, "call", return_value={"ok": False, "error": {"code": "unknown_action"}}), \
             mock.patch.object(wb, "list_tabs", return_value=[{"tabId": 1}, {"tabId": 2}]), \
             mock.patch.object(wb, "close_tab", return_value=True) as ct:
            self.assertEqual(wb.close_session("s2"), 2)
        self.assertEqual(ct.call_count, 2)


class TestSessionRegistry(unittest.TestCase):
    def _tf(self, reg_file: Path):
        from crawl import tenderfile as tf

        return tf, mock.patch.object(tf, "_WB_SESSIONS_FILE", reg_file)

    def test_register_and_forget_persist(self):
        with tempfile.TemporaryDirectory() as td:
            tf, patcher = self._tf(Path(td) / "sessions.json")
            with patcher:
                tf._register_session("tf-a")
                tf._register_session("tf-b")
                self.assertEqual(set(json.loads((Path(td) / "sessions.json").read_text(encoding="utf-8"))), {"tf-a", "tf-b"})
                tf._forget_session("tf-a")
                self.assertEqual(set(json.loads((Path(td) / "sessions.json").read_text(encoding="utf-8"))), {"tf-b"})
                tf._OPEN_BRIDGE_SESSIONS.clear()
                tf._save_session_registry({})

    def test_release_session_noop_when_never_opened(self):
        """单测里 mock 掉 _bridge_page 时不该产生任何额外桥调用。"""
        from crawl import tenderfile as tf

        tf._OPEN_BRIDGE_SESSIONS.clear()
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(tf, "_WB_SESSIONS_FILE", Path(td) / "s.json"), \
             mock.patch.object(tf, "close_session_safely") as c:
            self.assertEqual(tf.release_session("tf-never"), 0)
        c.assert_not_called()

    def test_stale_only_keeps_fresh_sessions(self):
        import time

        with tempfile.TemporaryDirectory() as td:
            tf, patcher = self._tf(Path(td) / "s.json")
            with patcher, mock.patch.object(tf, "close_session_safely", side_effect=lambda s: 1) as c:
                tf._OPEN_BRIDGE_SESSIONS.clear()
                tf._save_session_registry({"tf-old": time.time() - 7200, "tf-new": time.time()})
                closed = tf.close_bridge_tabs(stale_only_min=90)
                self.assertEqual(closed, 1)                       # 只清超龄的那个
                self.assertEqual([x[0][0] for x in c.call_args_list], ["tf-old"])
                self.assertEqual(set(tf._load_session_registry()), {"tf-new"})  # 新鲜的留着
                tf._save_session_registry({})

    def test_close_all_when_no_threshold(self):
        with tempfile.TemporaryDirectory() as td:
            tf, patcher = self._tf(Path(td) / "s.json")
            with patcher, mock.patch.object(tf, "close_session_safely", return_value=2):
                tf._OPEN_BRIDGE_SESSIONS.clear()
                tf._save_session_registry({"tf-a": 0.0, "tf-b": 0.0})
                self.assertEqual(tf.close_bridge_tabs(), 4)
                self.assertEqual(tf._load_session_registry(), {})

    def test_fetch_releases_session_even_on_error(self):
        from crawl import tenderfile as tf

        url = "https://www.chinabidding.cn/x.html"
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(tf, "_WB_SESSIONS_FILE", Path(td) / "s.json"), \
             mock.patch.object(tf, "_fetch_detail_via_bridge_inner", side_effect=RuntimeError("boom")), \
             mock.patch.object(tf, "close_session_safely", return_value=1) as c:
            tf._OPEN_BRIDGE_SESSIONS.clear()
            tf._save_session_registry({tf.bridge_session_name("chinabidding", url): 0.0})
            with self.assertRaises(RuntimeError):
                tf.fetch_detail_via_bridge("chinabidding", url)
            c.assert_called_once_with(tf.bridge_session_name("chinabidding", url))
            self.assertEqual(tf._load_session_registry(), {})
            tf._save_session_registry({})

    def test_session_name_is_deterministic(self):
        from crawl import tenderfile as tf

        a = tf.bridge_session_name("ggzy", "https://x/1.html")
        b = tf.bridge_session_name("ggzy", "https://x/1.html")
        c = tf.bridge_session_name("ggzy", "https://x/2.html")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertTrue(a.startswith("tf-ggzy-"))


class TestWatchCleansStaleSessions(unittest.TestCase):
    def test_clean_stale_sessions_closes_and_prunes(self):
        import time

        import wb_bridge

        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "sessions.json"
            f.write_text(json.dumps({"tf-old": time.time() - 7200, "tf-new": time.time()}), encoding="utf-8")
            with mock.patch.object(wb_bridge, "SESSIONS_FILE", f), \
                 mock.patch.object(wb_bridge.wb, "close_session", return_value=2) as cs:
                self.assertEqual(wb_bridge.clean_stale_sessions(stale_min=90), 2)
            cs.assert_called_once_with("tf-old")
            self.assertEqual(set(json.loads(f.read_text(encoding="utf-8"))), {"tf-new"})

    def test_clean_stale_sessions_without_file(self):
        import wb_bridge

        with mock.patch.object(wb_bridge, "SESSIONS_FILE", Path("no/such/file.json")):
            self.assertEqual(wb_bridge.clean_stale_sessions(), 0)

    def test_clean_all_with_zero_threshold(self):
        import wb_bridge

        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "s.json"
            f.write_text(json.dumps({"tf-a": 1.0, "tf-b": 2.0}), encoding="utf-8")
            with mock.patch.object(wb_bridge, "SESSIONS_FILE", f), \
                 mock.patch.object(wb_bridge.wb, "close_session", return_value=1):
                self.assertEqual(wb_bridge.clean_stale_sessions(stale_min=0), 2)
            self.assertEqual(json.loads(f.read_text(encoding="utf-8")), {})


class TestBrowserSourceFilter(unittest.TestCase):
    """浏览器源必须与 HTTP 内核同口径：8 城白名单 + 发布时间窗（无日期不丢）。"""

    def _filter(self, notices):
        from crawl import source_filter

        with mock.patch.object(source_filter, "only_target_cities", return_value=True), \
             mock.patch.object(source_filter, "target_city_names", return_value=["南京", "上海"]), \
             mock.patch.object(source_filter, "publish_date_range", return_value=("2026-07-01", None)):
            return source_filter.filter_notices(notices)

    def test_drops_offcity_and_out_of_window(self):
        class N:
            def __init__(self, city, pub):
                self.city = city
                self.publish_date = pub

        kept, dropped = self._filter([
            N("南京", "2026-08-01"),   # 留
            N("深圳", "2026-08-01"),   # 非白名单城市 → 丢
            N("上海", "2025-12-05"),   # 窗外 → 丢
            N("上海", ""),             # 无日期 → 留（与内核一致）
        ])
        self.assertEqual([n.city for n in kept], ["南京", "上海"])
        self.assertEqual(dropped, 2)

    def test_qianlima_filter_notices_delegates(self):
        import scripts.crawl_qianlima_wb as qlm  # noqa: F401

        from crawl import source_filter

        with mock.patch.object(source_filter, "filter_notices", return_value=([1], 2)) as f:
            self.assertEqual(qlm._filter_notices([1, 2, 3]), ([1], 2))
        f.assert_called_once()


if __name__ == "__main__":
    unittest.main()
