"""桥保活（心跳 + ensure-daemon）单测 —— 全 mock，不碰外网/DB。

设计要点：不依赖"改任务触发器"（需提权），用**心跳 + 按需拉起**解"守护者自己挂了没人管"。
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import wb_bridge  # noqa: E402


class TestWatchHeartbeat(unittest.TestCase):
    def _hb(self, td, ts):
        p = Path(td) / "wb_watch_heartbeat.json"
        p.write_text(json.dumps({"ts": ts, "pid": 1, "bridge_ok": True}), encoding="utf-8")
        return p

    def test_alive_when_fresh(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._hb(td, time.time())
            with mock.patch.object(wb_bridge, "WATCH_HEARTBEAT", p):
                self.assertTrue(wb_bridge.watch_alive(300))

    def test_dead_when_stale(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._hb(td, time.time() - 9999)
            with mock.patch.object(wb_bridge, "WATCH_HEARTBEAT", p):
                self.assertFalse(wb_bridge.watch_alive(300))

    def test_dead_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch.object(wb_bridge, "WATCH_HEARTBEAT", Path(td) / "nope.json"):
                self.assertFalse(wb_bridge.watch_alive(300))

    def test_dead_when_broken(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "bad.json"
            p.write_text("not json", encoding="utf-8")
            with mock.patch.object(wb_bridge, "WATCH_HEARTBEAT", p):
                self.assertFalse(wb_bridge.watch_alive(300))


class TestEnsureDaemon(unittest.TestCase):
    def test_noop_when_alive(self):
        with mock.patch.object(wb_bridge, "watch_alive", return_value=True):
            r = wb_bridge.ensure_daemon()
        self.assertFalse(r["started"])
        self.assertEqual(r["reason"], "watch_alive")

    def test_spawns_when_dead(self):
        with mock.patch.object(wb_bridge, "watch_alive", return_value=False), \
                mock.patch("subprocess.Popen") as popen:
            popen.return_value.pid = 1234
            r = wb_bridge.ensure_daemon()
        self.assertTrue(r["started"])
        self.assertEqual(r["pid"], 1234)
        self.assertEqual(popen.call_count, 1)

    def test_spawn_failure_is_honest(self):
        with mock.patch.object(wb_bridge, "watch_alive", return_value=False), \
                mock.patch("subprocess.Popen", side_effect=OSError("boom")):
            r = wb_bridge.ensure_daemon()
        self.assertFalse(r["started"])
        self.assertIn("boom", r["error"])


if __name__ == "__main__":
    unittest.main()
