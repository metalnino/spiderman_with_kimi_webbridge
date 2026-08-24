"""新增四站（乙方宝/千里马/工程帮/瑞达恒）源站单元测试（全离线）。"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


YFB_FIXTURE = """
<table id="treeTable">
<tbody>
<tr class="">
<td class="title-click-only-cell">
<a class="firstTdAAA" href="/inviteBid/detail/20260824_624820657.html" target="_blank">中国农业银行巴中分行营业办公场所环境<font color='#ff0000'>绿植租摆</font>项目公开招标公告</a>
</td>
<td class="text-align">招标公告</td>
<td class="text-align">巴中巴州区</td>
<td class="text-align">2026-08-24</td>
</tr>
<tr class="">
<td class="title-click-only-cell">
<a class="firstTdAAA" href="/inviteBid/detail/20260822_624511488.html" target="_blank">福州某单位绿化养护服务采购公告</a>
</td>
<td class="text-align">招标公告</td>
<td class="text-align">福州鼓楼区</td>
<td class="text-align">2026-08-22</td>
</tr>
</tbody>
</table>
"""

QLM_FIXTURE = {
    "code": 200,
    "status": 200,
    "msg": "OK",
    "data": {
        "rowCount": 2,
        "pagesCount": 1,
        "data": [
            {"contentid": 624885808, "progName": "结果", "updateTime": "2026-08-24",
             "popTitle": "渝富大厦2026年绿植租摆单位招投标", "showTitle": "渝富大厦2026年绿植租摆单位招投标",
             "url": "https://www.qianlima.com/bid-624885808.html",
             "originUrl": "http://www.qianlima.com/zb/detail/20260824_624885808.html",
             "areaName": "上海-上海"},
            {"contentid": 624820657, "progName": "公告", "updateTime": "2026-08-23",
             "popTitle": "南京某项目绿化养护", "showTitle": "南京某项目绿化养护",
             "url": "https://www.qianlima.com/bid-624820657.html",
             "originUrl": "http://www.qianlima.com/zb/detail/20260823_624820657.html",
             "areaName": "江苏-南京"},
        ],
    },
}


class TestYfbzb(unittest.TestCase):
    def test_parse_rows(self):
        from crawl.sources.yfbzb import YfbzbSource

        items = YfbzbSource._parse_rows(YfbzbSource(), YFB_FIXTURE, "绿植租摆")
        self.assertEqual(len(items), 2)
        self.assertIn("中国农业银行巴中分行", items[0].title)
        self.assertEqual(items[0].publish_date, "2026-08-24")
        self.assertEqual(items[0].region_text, "巴中巴州区")
        self.assertEqual(items[0].detail_url, "https://www.yfbzb.com/inviteBid/detail/20260824_624820657.html")
        self.assertEqual(items[0].notice_type, "招标公告")

    def test_fetch_flow(self):
        from crawl.sources.yfbzb import YfbzbSource

        src = YfbzbSource()
        with mock.patch.object(src.http, "get_text", return_value=YFB_FIXTURE), \
             mock.patch.object(src.http, "sleep", mock.MagicMock()), \
             mock.patch.dict("os.environ", {"SPIDER_YFBZB_MAX_PAGES": "1"}):  # P7：默认 3 页，旧用例锁 1 页
            items = list(src.fetch(["绿植租摆"], max_pages=1))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].keyword, "绿植租摆")


class TestQianlima(unittest.TestCase):
    def test_parse(self):
        from crawl.sources.qianlima import QianlimaSource

        items = QianlimaSource._parse(QianlimaSource(), QLM_FIXTURE, "绿植租摆")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].external_id, "624885808")
        self.assertEqual(items[0].city, "上海")
        self.assertEqual(items[0].notice_type, "结果")
        self.assertEqual(items[0].detail_url, "https://www.qianlima.com/bid-624885808.html")

    def test_fetch_flow(self):
        from crawl.sources.qianlima import QianlimaSource

        src = QianlimaSource()
        with mock.patch.object(src.http, "request", return_value=(200, json.dumps(QLM_FIXTURE).encode(), "")), \
             mock.patch.object(src.http, "sleep", mock.MagicMock()), \
             mock.patch.dict("os.environ", {"SPIDER_QIANLIMA_MAX_PAGES": "1"}):  # P7：默认 3 页，旧用例锁 1 页
            items = list(src.fetch(["绿植租摆"], max_pages=1))
        self.assertEqual(len(items), 2)


class TestTgnet(unittest.TestCase):
    def test_parse_items(self):
        from scripts.crawl_tgnet_pw import parse_items

        raw = [
            {"code": "RBCXSH", "title": "人保财险上海分公司综合部职场绿化绿植项目",
             "href": "https://www.tgnet.com/project/RBCXSH/",
             "row": "人保财险上海分公司综合部职场绿化绿植项目 工程分包 -- 2025-12-05"},
            {"code": "HCWSCL2", "title": "合川污水处理厂厂区绿植更新项目",
             "href": "https://www.tgnet.com/project/HCWSCL2/",
             "row": "合川污水处理厂厂区绿植更新项目（重庆市渝西水务有限公司） 前期立项 -- 2025-11-11"},
        ]
        items = parse_items(raw, "绿植租摆")
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].external_id, "RBCXSH")
        self.assertEqual(items[0].city, "上海")
        self.assertEqual(items[0].notice_type, "工程分包")
        self.assertEqual(items[0].publish_date, "2025-12-05")
        self.assertEqual(items[1].notice_type, "前期立项")


class TestRccchina(unittest.TestCase):
    def test_register_wall_honest(self):
        from crawl.sources.base import SourceError
        from crawl.sources.rccchina import RccchinaSource

        src = RccchinaSource()
        with mock.patch("crawl.sources.rccchina.open_todo") as todo, mock.patch(
            "crawl.sources.rccchina.cookie_store.cookie_header", return_value=None
        ):
            with self.assertRaises(SourceError) as ctx:
                list(src.fetch(["绿植租摆"], max_pages=1))
        self.assertIn("register_wall", str(ctx.exception))
        self.assertTrue(todo.called)  # 注册墙登记待办，绝不伪造数据

    def test_cookie_present_honest_unmapped(self):
        """已有 Cookie 但搜索接口未接线：如实报错，不重复挂待办、不编造 0。"""
        from crawl.sources.base import SourceError
        from crawl.sources.rccchina import RccchinaSource

        src = RccchinaSource()
        with mock.patch("crawl.sources.rccchina.open_todo") as todo, mock.patch(
            "crawl.sources.rccchina.cookie_store.cookie_header", return_value="sid=abc; token=x"
        ):
            with self.assertRaises(SourceError) as ctx:
                list(src.fetch(["绿植租摆"], max_pages=1))
        self.assertIn("cookie_ok_api_unmapped", str(ctx.exception))
        self.assertFalse(todo.called)  # 已有 cookie 不再重复挂待办


class TestRouting(unittest.TestCase):
    def test_registry_has_four_sites(self):
        from crawl.sources import REGISTRY

        for pid in ("yfbzb", "qianlima", "tgnet", "rccchina"):
            self.assertIn(pid, REGISTRY, f"{pid} 应注册进 SOURCE_REGISTRY")

    def test_browser_routes_tgnet_playwright(self):
        from crawl import collector_employee as ce

        self.assertEqual(ce.BROWSER_ROUTES["tgnet"]["route"], "playwright")
        self.assertEqual(ce.BROWSER_ROUTES["tgnet"]["module"], "crawl_tgnet_pw")

    def test_detail_modes(self):
        from crawl import tenderfile as tf

        self.assertEqual(tf.DETAIL_MODES["yfbzb"], "http")
        self.assertEqual(tf.DETAIL_MODES["qianlima"], "bridge")
        self.assertEqual(tf.DETAIL_MODES["tgnet"], "bridge")
        self.assertEqual(tf.DETAIL_MODES["rccchina"], "blocked_regwall")

    def test_fetch_tenderfile_regwall_honest(self):
        from crawl import tenderfile as tf

        res = tf.fetch_tenderfile("rccchina", "https://bid.rccchina.com/x")
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "detail_register_wall")
        self.assertIsNone(res["tenderFile"])

    def test_platforms_config_has_four_sites(self):
        from crawl import collector_employee as ce

        plats = {e["id"]: e for e in ce.load_platforms()}
        self.assertTrue(plats["yfbzb"]["enabled"])
        self.assertEqual(plats["yfbzb"]["route"], "http")
        self.assertEqual(plats["qianlima"]["route"], "http")
        self.assertEqual(plats["tgnet"]["route"], "playwright")
        self.assertEqual(plats["rccchina"]["route"], "http")


if __name__ == "__main__":
    unittest.main(verbosity=2)
