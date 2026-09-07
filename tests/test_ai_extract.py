"""AI 详情字段抽取单测（mock HTTP，不碰外网/DB）。"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crawl import ai_extract as ai  # noqa: E402


class _FakeResp:
    def __init__(self, obj):
        self._data = json.dumps(obj).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._data


class TestParseJson(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(ai._parse_json('{"buyer":"某医院"}'), {"buyer": "某医院"})

    def test_code_fence(self):
        self.assertEqual(ai._parse_json('```json\n{"buyer":"某医院"}\n```')["buyer"], "某医院")

    def test_noise_around(self):
        self.assertEqual(ai._parse_json('好的，结果：{"buyer":"某医院"} 结束')["buyer"], "某医院")

    def test_malformed(self):
        self.assertEqual(ai._parse_json("not json"), {})

    def test_empty(self):
        self.assertEqual(ai._parse_json(""), {})


class TestSanitize(unittest.TestCase):
    def test_known_fields_only(self):
        d = ai._sanitize(
            {"buyer": "某医院", "agency": "某代理", "junk": "x", "winner": None,
             "amount_text": "12.5万元", "deadline": "2026-09-01"},
            None,
        )
        self.assertEqual(set(d.keys()), set(ai.KNOWN_FIELDS))
        self.assertEqual(d["buyer"], "某医院")
        self.assertEqual(d["amount_text"], "12.5万元")
        self.assertIsNone(d["winner"])

    def test_null_like_values(self):
        d = ai._sanitize({"buyer": "无", "agency": "null", "deadline": "不详"}, ["buyer", "agency", "deadline"])
        self.assertIsNone(d["buyer"])
        self.assertIsNone(d["agency"])
        self.assertIsNone(d["deadline"])


class TestExtractFields(unittest.TestCase):
    def test_success(self):
        resp = {"choices": [{"message": {"content": '{"buyer":"某医院","agency":"某代理",'
                          '"amount_text":"12.5万元","deadline":"2026-09-01","winner":"某园林公司"}'}}]}
        cfg = {"enabled": True, "api_key": "k", "endpoint": "https://x", "model": "m",
               "max_tokens": 800, "timeout_sec": 5}
        with mock.patch.object(ai, "load_cfg", return_value=cfg), \
                mock.patch("urllib.request.urlopen", return_value=_FakeResp(resp)):
            d = ai.extract_fields("某医院 绿植租摆 采购公告 12.5万元")
        self.assertEqual(d["buyer"], "某医院")
        self.assertEqual(d["winner"], "某园林公司")
        self.assertEqual(d["deadline"], "2026-09-01")

    def test_disabled(self):
        with mock.patch.object(ai, "load_cfg", return_value={"enabled": False}):
            self.assertEqual(ai.extract_fields("text"), {})

    def test_network_fail(self):
        cfg = {"enabled": True, "api_key": "k", "endpoint": "https://x", "model": "m",
               "max_tokens": 800, "timeout_sec": 5}
        with mock.patch.object(ai, "load_cfg", return_value=cfg), \
                mock.patch("urllib.request.urlopen", side_effect=Exception("boom")):
            self.assertEqual(ai.extract_fields("text"), {})

    def test_empty_text(self):
        self.assertEqual(ai.extract_fields(""), {})
        self.assertEqual(ai.extract_fields(None), {})

    def test_bad_model_output(self):
        resp = {"choices": [{"message": {"content": "没有 JSON"}}]}
        cfg = {"enabled": True, "api_key": "k", "endpoint": "https://x", "model": "m",
               "max_tokens": 800, "timeout_sec": 5}
        with mock.patch.object(ai, "load_cfg", return_value=cfg), \
                mock.patch("urllib.request.urlopen", return_value=_FakeResp(resp)):
            self.assertEqual(ai.extract_fields("text"), {})


if __name__ == "__main__":
    unittest.main()
