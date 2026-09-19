"""源头追溯员单测（纯函数 + 注入式假数据；不碰外网、不碰真库）。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from crawl import origin_hints  # noqa: E402
from crawl import origin_trace as ot  # noqa: E402
from crawl.origin_portals import (  # noqa: E402
    classify_domain, detail_url_for, domain_of, load_registry, match_portal
)

CHNG_BODY = (
    "上海职场绿植租摆服务采购询比采购公告 采购编号：HNFZ2026-09-2-00396 "
    "本项目：上海职场绿植租摆服务采购，采购人为：华能天成融资租赁有限公司。"
    "联系电话：16643414180 电子邮箱：baonike@huanengleasing.com 联系人：包经理 "
    "本次采购公告在中国华能集团电子商务平台（https://ec.chng.com.cn/）发布。"
)


class TestHints(unittest.TestCase):
    def test_rule_hints_full(self):
        h = origin_hints.rule_hints(CHNG_BODY, "上海职场绿植租摆服务采购询比采购公告")
        self.assertEqual(h["buyer"], "华能天成融资租赁有限公司")
        self.assertEqual(h["projectCode"], "HNFZ2026-09-2-00396")
        self.assertIn("huanengleasing.com", h["emailDomains"])
        self.assertIn("https://ec.chng.com.cn/", h["urls"])
        self.assertIn("电子商务平台", h["portalWords"])

    def test_rule_hints_skips_public_mailbox(self):
        h = origin_hints.rule_hints("邮箱：a@qq.com 邮箱：b@163.com 邮箱：c@huanengleasing.com")
        self.assertEqual(h["emailDomains"], ["huanengleasing.com"])

    def test_buyer_from_title_when_body_missing(self):
        h = origin_hints.rule_hints("", "华能天成融资租赁有限公司上海职场绿植租摆服务项目采购变更询比采购公告")
        self.assertEqual(h["buyer"], "华能天成融资租赁有限公司")

    def test_fill_missing_does_not_overwrite(self):
        base = {"buyer": None, "projectCode": "X1", "emailDomains": [], "urls": [], "portalWords": []}
        out = origin_hints.fill_missing(base, {"buyer": "甲公司", "projectCode": "X2",
                                               "emailDomains": ["a.com"], "urls": ["http://a"], "portalWords": []})
        self.assertEqual(out["buyer"], "甲公司")
        self.assertEqual(out["projectCode"], "X1")  # 已有值不被覆盖
        self.assertEqual(out["emailDomains"], ["a.com"])

    def test_search_queries_orders_and_dedupes(self):
        h = {"buyer": "华能天成融资租赁有限公司", "projectCode": "HNFZ2026-09-2-00396"}
        qs = origin_hints.search_queries(h, "上海职场绿植租摆服务采购询比采购公告")
        self.assertTrue(qs[0].startswith('"HNFZ'))
        self.assertTrue(any("招标采购交易平台" in q for q in qs))  # 平台发现型检索词必须存在
        self.assertEqual(len(qs), len(set(qs)))

    def test_search_queries_without_buyer(self):
        qs = origin_hints.search_queries({}, "上海职场绿植租摆服务采购询比采购公告")
        self.assertTrue(qs)
        self.assertTrue(any("交易平台" in q for q in qs))


class TestGarbled(unittest.TestCase):
    def test_garbled_ratio_on_binary_junk(self):
        junk = "".join(chr(i) for i in range(1, 40)) * 20
        self.assertGreater(ot.garbled_ratio(junk), 0.02)
        self.assertFalse(ot.is_usable_body(junk))

    def test_usable_body_ok(self):
        self.assertTrue(ot.is_usable_body(CHNG_BODY * 3))

    def test_login_wall_not_usable(self):
        text = "以下内容，如需查看详细内容，请先 免费注册 ， 已注册的用户请 登录 后查看 " + "招标编号 立即注册查看 " * 30
        self.assertFalse(ot.is_usable_body(text))

    def test_better_than(self):
        self.assertTrue(ot._better_than("x" * 100, None))
        self.assertTrue(ot._better_than("x" * 100, "y" * 10))
        self.assertFalse(ot._better_than("x" * 10, "y" * 100))
        self.assertFalse(ot._better_than("", "y" * 100))


class TestTitleScore(unittest.TestCase):
    def test_exact_is_one(self):
        t = "上海职场绿植租摆服务采购询比采购公告"
        self.assertEqual(ot.title_score(t, t), 1.0)

    def test_change_notice_scores_lower(self):
        a = "上海职场绿植租摆服务采购询比采购公告"
        b = "华能天成融资租赁有限公司上海职场绿植租摆服务项目采购变更询比采购公告"
        self.assertLess(ot.title_score(a, b), 1.0)

    def test_unrelated_low(self):
        self.assertLess(ot.title_score("上海职场绿植租摆服务", "合肥市公安局大楼消防改造"), 0.3)


class TestMirrorAndDate(unittest.TestCase):
    def test_brand_signal(self):
        self.assertTrue(ot.mirror_signals("中国采购与招标网 欢迎您 登录后查看 注册后查看"))

    def test_list_page_signal_short_page(self):
        text = "公告 " * 15
        self.assertTrue(any(s.startswith("list_page") for s in ot.mirror_signals(text)))

    def test_long_doc_with_many_words_not_list_page(self):
        text = ("公告 " * 15) + ("正文内容 " * 800)
        self.assertFalse(any(s.startswith("list_page") for s in ot.mirror_signals(text)))

    def test_date_consistent(self):
        page = "发布时间：2026-09-14 开标时间 2026-09-17"
        self.assertTrue(ot.date_consistent(page, "2026-09-14 12:16:51"))
        self.assertFalse(ot.date_consistent(page, "2026-07-17 00:00:00"))

    def test_date_consistent_when_no_date(self):
        self.assertTrue(ot.date_consistent("没有任何日期", "2026-09-14"))


class TestRegistry(unittest.TestCase):
    def test_registry_loads(self):
        reg = load_registry()
        self.assertTrue(reg["portals"])
        self.assertIn("qianlima.com", reg["aggregatorDomains"])

    def test_classify_domain(self):
        self.assertEqual(classify_domain("https://ec.chng.com.cn/channel/home/"), "head")
        self.assertEqual(classify_domain("https://www.qianlima.com/bid-1.html"), "aggregator")
        self.assertEqual(classify_domain("https://www.ccgp.gov.cn/x.htm"), "gov")
        self.assertEqual(classify_domain("https://unknown-corp.example/x"), "unknown")

    def test_match_portal_by_buyer_keyword(self):
        p = match_portal("华能天成融资租赁有限公司上海职场绿植租摆服务项目采购变更询比采购公告", {})
        self.assertIsNotNone(p)
        self.assertEqual(p["id"], "chng")

    def test_match_portal_by_hint_domain(self):
        p = match_portal("某项目公告", {"urls": ["https://ec.chng.com.cn/channel/home/#/detail?id=1"]})
        self.assertEqual(p["id"], "chng")

    def test_detail_url_for(self):
        p = match_portal("华能某项目", {})
        self.assertEqual(detail_url_for(p, {"key": "12930997"}),
                         "https://ec.chng.com.cn/channel/home/#/detail?id=12930997")
        self.assertIsNone(detail_url_for(p, {"key": ""}))

    def test_domain_of(self):
        self.assertEqual(domain_of("https://bid.easternairports.com:1443/a/b"), "bid.easternairports.com")


class TestCandidateFilter(unittest.TestCase):
    def test_filters_aggregator_and_info_sites(self):
        results = [
            {"title": "A", "url": "https://www.qianlima.com/bid-1.html"},
            {"title": "B", "url": "https://www.qcc.com/firm/x.html"},
            {"title": "C", "url": "https://www.ccgp.gov.cn/a.htm"},
            {"title": "D", "url": "https://ec.chng.com.cn/channel/home/#/detail?id=1"},
        ]
        cands = ot._candidate_filter(results, registry=load_registry())
        domains = [c["domain"] for c in cands]
        self.assertNotIn("www.qianlima.com", domains)
        self.assertNotIn("www.qcc.com", domains)
        self.assertEqual(cands[0]["domain"], "ec.chng.com.cn")  # head 排最前
        self.assertEqual(cands[0]["score"], 1.0)


class TestFetchAndVerify(unittest.TestCase):
    def _fetch(self, text, title="公告页", **kw):
        return lambda url, **_: {"ok": True, "error": None, "summary": text[:500], "text": text,
                                 "pageTitle": title, "attachments": [], "session": "s"}

    def test_accepts_matching_page(self):
        title = "上海职场绿植租摆服务采购询比采购公告"
        text = "上海职场绿植租摆服务采购询比采购公告 采购人：华能天成融资租赁有限公司 2026-09-14"
        got = ot._fetch_and_verify("https://ec.chng.com.cn/detail?id=1", title=title,
                                   hints={"buyer": "华能天成融资租赁有限公司"},
                                   publish_date="2026-09-14", portal_id="chng", wait_sec=0,
                                   download=False, min_score=0.55, fetch_fn=self._fetch(text))
        self.assertTrue(got["ok"])

    def test_rejects_non_source_domain(self):
        got = ot._fetch_and_verify("https://www.qcc.com/firm/x.html", title="某项目公告",
                                   hints={}, publish_date="2026-09-14", portal_id="x", wait_sec=0,
                                   download=False, min_score=0.5, fetch_fn=self._fetch(CHNG_BODY))
        self.assertFalse(got["ok"])
        self.assertIn("non_source_domain", got["error"])

    def test_rejects_mirror_page(self):
        text = "中国采购与招标网 " + CHNG_BODY + " 登录后查看 注册后查看"
        got = ot._fetch_and_verify("https://example.com/a", title="上海职场绿植租摆服务采购询比采购公告",
                                   hints={}, publish_date="2026-09-14", portal_id="x", wait_sec=0,
                                   download=False, min_score=0.5, fetch_fn=self._fetch(text))
        self.assertFalse(got["ok"])
        self.assertIn("mirror", got["error"])

    def test_rejects_date_mismatch(self):
        text = "上海职场绿植租摆服务采购询比采购公告 2026-07-17 发布"
        got = ot._fetch_and_verify("https://example.com/a", title="上海职场绿植租摆服务采购询比采购公告",
                                   hints={}, publish_date="2026-09-14", portal_id="x", wait_sec=0,
                                   download=False, min_score=0.5, fetch_fn=self._fetch(text))
        self.assertFalse(got["ok"])
        self.assertEqual(got["error"], "date_mismatch")

    def test_rejects_missing_project_anchor(self):
        text = "完全无关的页面内容 " * 40
        got = ot._fetch_and_verify("https://example.com/a", title="上海职场绿植租摆服务采购询比采购公告",
                                   hints={}, publish_date=None, portal_id="x", wait_sec=0,
                                   download=False, min_score=0.1, fetch_fn=self._fetch(text))
        self.assertFalse(got["ok"])
        self.assertEqual(got["error"], "no_project_anchor")


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.sql = ""

    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        # 兄弟公告查询走 title LIKE，这里一律返回空（避免测试碰真库语义）
        return [] if "title LIKE" in self.sql else self._rows

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCursor(self._rows)

    def close(self):
        pass


class TestTraceOneWithInjectedIO(unittest.TestCase):
    """端到端（注入假检索/假抓取）：验证「注册表命中 → 站内检索 → 取详情 → 落库记录」这条主链。"""

    def _run(self, rows, search_rows):
        db = _FakeDB(rows)
        return ot.trace_one(
            project_key="k1", use_ai=False, download=False, db=db,
            search_portal_fn=lambda portal, kw: search_rows,
            search_web_fn=lambda q: [],
            fetch_fn=lambda url, **_: {
                "ok": True, "error": None,
                "summary": "上海职场绿植租摆服务采购询比采购公告 " + CHNG_BODY,
                "text": "上海职场绿植租摆服务采购询比采购公告 " + CHNG_BODY,
                "pageTitle": "上海职场绿植租摆服务采购询比采购公告",
                "attachments": [], "session": "s",
            },
        )

    def test_happy_path_via_registry(self):
        title = "华能天成融资租赁有限公司上海职场绿植租摆服务项目采购询比采购公告"
        rows = [{
            "id": 50343, "source_id": "yfbzb", "title": title,
            "city": "上海", "publish_date": "2026-09-14 00:00:00", "notice_stage": "bidding",
            "detail_url": "https://www.yfbzb.com/x.html", "summary": "",
            "tenderfile_path": None, "detail_status": None, "original_url": None,
            "origin_source": None, "buyer": None, "project_code": None,
        }]
        rec = self._run(rows, [{"key": "12930997", "title": title}])
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["portalId"], "chng")
        self.assertIn("id=12930997", rec["detailUrl"])
        self.assertGreater(rec["body"]["chars"], 100)
        self.assertEqual(rec["method"], "portal_registry")

    def test_not_found_when_search_returns_nothing(self):
        rows = [{
            "id": 1, "source_id": "chinabidding",
            "title": "华能天成融资租赁有限公司上海职场绿植租摆服务项目采购询比采购公告",
            "city": "上海", "publish_date": "2026-09-14 00:00:00", "notice_stage": "bidding",
            "detail_url": "https://www.chinabidding.cn/x.html", "summary": "",
            "tenderfile_path": None, "detail_status": None, "original_url": None,
            "origin_source": None, "buyer": None, "project_code": None,
        }]
        rec = self._run(rows, [])
        self.assertIn(rec["status"], ("not_found", "no_hint"))
        self.assertIsNone(rec["detailUrl"])

    def test_source_is_origin_short_circuits(self):
        rows = [{
            "id": 9, "source_id": "ccgp", "title": "某政府采购项目公开招标公告",
            "city": "南京", "publish_date": "2026-09-14 00:00:00", "notice_stage": "bidding",
            "detail_url": "https://www.ccgp.gov.cn/cggg/x.htm", "summary": "",
            "tenderfile_path": None, "detail_status": None, "original_url": None,
            "origin_source": None, "buyer": None, "project_code": None,
        }]
        rec = self._run(rows, [])
        self.assertTrue(rec["sourceIsOrigin"])
        self.assertEqual(rec["status"], "ok")
        self.assertEqual(rec["method"], "source_is_origin")


if __name__ == "__main__":
    unittest.main()
