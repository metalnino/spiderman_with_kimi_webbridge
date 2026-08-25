"""增量简报邮件：渲染/主题/摘要/发送封装 单测（全离线，不发真信）。"""
from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from crawl import mail_report as mr  # noqa: E402
from scripts import email_gateway as eg  # noqa: E402


def _items(n=3):
    return [
        {
            "title": f"某单位绿植租摆采购项目 {i}",
            "platform": "ccgp",
            "city": "南京",
            "keyword": "绿植租摆",
            "publish_date": "2026-08-27 10:00:00",
            "url": f"https://example.com/d/{i}",
        }
        for i in range(n)
    ]


def _report(new=3):
    return {
        "runId": "collector-20260827T110000",
        "startedAt": "2026-08-27T11:00:00",
        "finishedAt": "2026-08-27T11:03:00",
        "metrics": {
            "fetched_count": 40,
            "dedup_new_count": new,
            "platform_success_rate": {"ccgp": 1.0},
            "empty_platforms": [],
            "blocked_count": 0,
            "elapsed_ms": 180000,
            "detail_fetch_success_rate": None,
        },
        "perPlatform": [{"platform": "ccgp", "status": "success"}],
        "notes": ["tenderFile 口径说明"],
    }


class TestRender(unittest.TestCase):
    def test_render_contains_summary_and_rows(self):
        html = mr.render_html(mr.build_summary_from_report(_report(), _items()), _items())
        self.assertIn("绿植招采简报", html)
        self.assertIn("本轮新增", html)
        self.assertIn("城市分布", html)
        self.assertIn("关键词分布", html)
        self.assertIn("南京", html)
        self.assertIn("绿植租摆", html)
        self.assertIn("某单位绿植租摆采购项目 0", html)
        self.assertIn('href="https://example.com/d/0"', html)

    def test_render_empty(self):
        html = mr.render_html(mr.build_summary_from_report(_report(new=0), []), [])
        self.assertIn("本轮无新增公告", html)

    def test_render_escapes_html_in_title(self):
        items = [_items(1)[0]]
        items[0]["title"] = '<script>alert("x")</script>'
        html = mr.render_html({"new": 1}, items)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class TestSubject(unittest.TestCase):
    def test_subject_new_count_and_city(self):
        s = mr.build_subject(mr.build_summary_from_report(_report(), _items()), _items())
        self.assertIn("绿植招采简报", s)
        self.assertIn("新增 3 条", s)
        self.assertIn("南京 3", s)

    def test_subject_zero_new(self):
        s = mr.build_subject({"started_at": "2026-08-27T11:00:00", "new": 0}, [])
        self.assertIn("新增 0 条", s)


class TestNormalizeAndSummary(unittest.TestCase):
    def test_normalize_items(self):
        raw = [{
            "title": "标题", "source_name": "中国政府采购网", "source_id": "ccgp",
            "city": "上海", "keyword": "绿化养护", "publish_date": "2026-08-27 09:00:00",
            "detail_url": "https://x/y", "official_url": None,
        }]
        it = mr._normalize_items(raw)[0]
        self.assertEqual(it["platform"], "中国政府采购网")
        self.assertEqual(it["url"], "https://x/y")
        self.assertEqual(it["city"], "上海")

    def test_build_summary_from_report(self):
        s = mr.build_summary_from_report(_report(), _items(2))
        self.assertEqual(s["new"], 2)
        self.assertEqual(s["fetched"], 40)
        self.assertEqual(s["platforms_ok"], 1)
        self.assertEqual(s["failed_platforms"], [])

    def test_build_summary_from_http(self):
        results = [
            {"source_id": "ccgp", "status": "success", "raw_total": 5, "notices": [], "error": None},
            {"source_id": "tgnet", "status": "error", "raw_total": 0, "notices": [], "error": "http 403 blocked"},
        ]
        s = mr.build_summary_from_http(results, _items(2))
        self.assertEqual(s["fetched"], 5)
        self.assertEqual(s["new"], 2)
        self.assertEqual(s["platforms_ok"], 1)
        self.assertEqual(s["failed_platforms"], ["tgnet"])
        self.assertEqual(s["blocked"], 1)


class TestSend(unittest.TestCase):
    def test_send_briefing_disabled_by_env(self):
        with mock.patch.dict(os.environ, {"SPIDER_NO_EMAIL": "1"}):
            r = mr.send_briefing(mr.build_summary_from_report(_report(), _items()), _items())
        self.assertFalse(r["ok"])
        self.assertTrue(r.get("skipped"))

    def test_send_html_builds_multipart_and_smtp(self):
        fake_smtp = mock.MagicMock()
        with mock.patch.object(eg, "creds", return_value=("u", "p")), \
             mock.patch.object(eg, "proxy", return_value=None), \
             mock.patch.object(eg.smtplib, "SMTP_SSL", return_value=fake_smtp):
            r = eg.send_html("to@x.com", "主题", "<b>加粗</b>", body_text="纯文本")
        self.assertTrue(r["ok"])
        sent_msg = fake_smtp.__enter__.return_value.send_message.call_args[0][0]
        self.assertTrue(sent_msg.is_multipart())
        self.assertEqual(sent_msg.get_content_subtype(), "alternative")

    def test_send_briefing_never_raises_on_smtp_error(self):
        with mock.patch.object(eg, "send_html", side_effect=RuntimeError("boom")):
            r = mr.send_briefing({"new": 1}, _items(1))
        self.assertFalse(r["ok"])
        self.assertIn("RuntimeError", r["error"])


if __name__ == "__main__":
    unittest.main()
