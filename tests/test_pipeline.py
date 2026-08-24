"""P6 管道接线：采集员交接物落盘 单测（不碰外网/DB）。"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _load_collector_run():
    spec = importlib.util.spec_from_file_location("collector_run", ROOT / "scripts" / "collector_run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestCollectorHandoff(unittest.TestCase):
    def test_handoff_writes_latest_and_archive(self):
        with tempfile.TemporaryDirectory() as td:
            mod = _load_collector_run()
            fake = {
                "output": [{
                    "title": "某项目招标公告", "platform": "ccgp", "url": "https://x",
                    "publishTime": "2026-08-01T09:00:00+08:00", "region": "南京",
                    "amount": None, "summary": None,
                    "dedupId": "md5abc", "tenderFile": None,
                }],
                "report": {"runId": "collector-20260823T000000"},
            }
            with mock.patch.object(mod, "HANDOFF_DIR", Path(td) / "handoffs" / "collector"):
                latest = mod._write_handoff(fake)
            self.assertTrue(Path(latest).exists())
            payload = json.loads(Path(latest).read_text(encoding="utf-8"))
            self.assertEqual(payload["runId"], "collector-20260823T000000")
            self.assertEqual(payload["implements"], "collector/v1.2.0")
            self.assertEqual(payload["items"], fake["output"])
            archive = Path(td) / "handoffs" / "collector" / "collector-20260823T000000.json"
            self.assertTrue(archive.exists())
            # 交接物 items 与契约 output 同构（管道契约铁律：collector.output.items[i] == parser.input）
            item = payload["items"][0]
            for k in ("title", "platform", "url", "publishTime", "region", "amount", "dedupId", "tenderFile"):
                self.assertIn(k, item)


if __name__ == "__main__":
    unittest.main()
