"""深圳阳光采购平台（szexgrp）源适配器单测（mock HTTP，不碰外网）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from crawl.sources.szexgrp import SzexgrpSource  # noqa: E402


def _fake_page():
    return {
        "code": 200,
        "data": {
            "content": [
                {"title": "某单位绿植租摆服务采购公告", "noticeTitle": "某单位绿植租摆服务采购公告",
                 "bidSectionNumber": "YG26ZG0051939-01", "noticeTypeCode": "ygcg_cggg",
                 "noticeTypeName": "采购公告", "releaseTime": "2026-09-16 14:10:00",
                 "id": 20641929, "contentId": 20641929},
                {"title": "另一项目绿化养护结果公示", "noticeTitle": "另一项目绿化养护结果公示",
                 "bidSectionNumber": "TQJG20260821FW0014", "noticeTypeCode": "ygcg_jggs",
                 "noticeTypeName": "结果公示", "releaseTime": "2026-09-14 18:00:00",
                 "id": 20637920, "contentId": 20637920},
                {"title": "某邀请招标邀请函", "noticeTitle": "某邀请招标邀请函",
                 "bidSectionNumber": "YG26YQ0001-01", "noticeTypeCode": "ygcg_yqh",
                 "noticeTypeName": "邀请函", "releaseTime": "2026-09-15 10:00:00",
                 "id": 20640000, "contentId": 20640000},  # 邀请投标：非公开招标，应被类型白名单丢掉
                {"title": "无编号记录", "noticeTitle": "无编号记录", "id": None},  # 应被跳过/无 detail_url
            ],
            "totalElements": 2,
        },
    }


class TestSzexgrpSource(unittest.TestCase):
    def test_parse_notices(self):
        src = SzexgrpSource()
        with mock.patch.dict("os.environ", {"SPIDER_SZEXGRP_MAX_PAGES": "1"}), \
                mock.patch.object(src.http, "get_json", return_value=_fake_page()), \
                mock.patch.object(src.http, "sleep"):
            items = list(src.fetch(["绿植租摆"], max_pages=1))
        # 3 条里最后一条 id=None 无 detail_url 仍应入库（title 合法），但 detail_url=None
        self.assertGreaterEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first.source_id, "szexgrp")
        self.assertEqual(first.title, "某单位绿植租摆服务采购公告")
        self.assertEqual(first.city, "深圳")
        self.assertEqual(first.publish_date, "2026-09-16 14:10:00")
        self.assertEqual(first.notice_type, "采购公告")
        self.assertEqual(first.external_id, "20641929")
        self.assertIn("/jyxxDetails.htm?bidSectionNumber=YG26ZG0051939-01", first.detail_url)
        self.assertTrue(first.detail_url.endswith("code=cggg"))
        # 类型白名单：邀请函（邀请投标）必须被丢掉，只留公开采购周期的类型
        self.assertNotIn("邀请函", {n.notice_type for n in items})

    def test_error_on_bad_code(self):
        from crawl.sources.base import SourceError

        src = SzexgrpSource()
        with mock.patch.dict("os.environ", {"SPIDER_SZEXGRP_MAX_PAGES": "1"}), \
                mock.patch.object(src.http, "get_json", return_value={"code": 500, "msg": "boom"}), \
                mock.patch.object(src.http, "sleep"):
            with self.assertRaises(SourceError):
                list(src.fetch(["绿植租摆"], max_pages=1))


class TestSzexgrpDetail(unittest.TestCase):
    def test_detail_parse_from_api(self):
        from crawl.tenderfile import _fetch_szexgrp_http
        from crawl.http_session import HttpSession

        fake = {"code": 200, "data": {"noticeList": [{
            "bidSectionNumber": "YG26ZG0051939-01",
            "bidSectionName": "某项目",
            "noticeContent": "<div><p>项目名称：某项目</p><p>采购人：某单位</p><p>预算金额：12.5万元</p></div>",
        }]}}
        h = HttpSession("szexgrp")
        url = "https://ygcg.szexgrp.com/jyxxDetails.htm?bidSectionNumber=YG26ZG0051939-01&contentId=1&code=cggg"
        with mock.patch.object(h, "get_json", return_value=fake):
            out = _fetch_szexgrp_http(url, h)
        self.assertTrue(out["ok"])
        self.assertEqual(out["fields"]["project_code"], "YG26ZG0051939-01")
        self.assertEqual(out["fields"]["buyer"], "某单位")
        self.assertEqual(out["fields"]["amount_text"], "12.5万元")
        self.assertIn("某项目", out["summary"])

    def test_detail_no_section_code(self):
        from crawl.tenderfile import _fetch_szexgrp_http
        from crawl.http_session import HttpSession

        out = _fetch_szexgrp_http("https://ygcg.szexgrp.com/jyxxDetails.htm", HttpSession("szexgrp"))
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "szexgrp_no_section_code")


class TestRegistration(unittest.TestCase):
    def test_registered_and_order(self):
        from crawl.sources import REGISTRY, SOURCE_ORDER

        self.assertIn("szexgrp", REGISTRY)
        self.assertIn("szexgrp", SOURCE_ORDER)


if __name__ == "__main__":
    unittest.main()
