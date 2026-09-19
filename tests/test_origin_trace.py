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

    def test_search_queries_buyer_first(self):
        """实测口径：「主体名 + 采购公告」是唯一稳定把一手源顶到首屏的形态，必须排第一。"""
        h = {"buyer": "温州银行股份有限公司"}
        qs = origin_hints.search_queries(h, "温州银行股份有限公司关于杭州大楼绿植租摆养护服务项目的中标(成交)结果公告")
        self.assertEqual(qs[0], "温州银行股份有限公司 采购公告")
        self.assertEqual(len(qs), len(set(qs)))
        self.assertTrue(all("原始公告" not in q and "交易平台" not in q for q in qs))  # 实测无效词已删

    def test_search_queries_without_buyer(self):
        qs = origin_hints.search_queries({}, "上海职场绿植租摆服务采购询比采购公告")
        self.assertTrue(qs)
        self.assertTrue(all("采购公告" not in q or "上海" in q for q in qs))

    def test_looks_like_origin_domain(self):
        f = origin_hints.looks_like_origin_domain
        self.assertTrue(f("https://www.ccgp.gov.cn/a.htm"))            # gov
        self.assertTrue(f("https://ec.chng.com.cn/x"))                 # 已登记 head
        self.assertTrue(f("https://czju.suzhou.gov.cn/zfcg/x"))
        self.assertFalse(f("https://www.qianlima.com/bid-1.html"))     # 聚合站
        self.assertFalse(f("https://random-shop.example/x"))


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


class TestMethodFixes(unittest.TestCase):
    """本轮实测暴露的方法缺陷对应的回归用例（每条都对应一个真实失败案例）。"""

    def test_szexgrp_is_own_platform_not_aggregator(self):
        # 自有平台 ≠ 聚合站：深圳交易集团自己的平台，同时也在我们的采集源里
        self.assertEqual(classify_domain("https://ygcg.szexgrp.com/jyxxDetails.htm?x=1"), "platform")

    def test_is_site_root(self):
        self.assertTrue(ot._is_site_root("https://www.wzbank.cn/"))
        self.assertTrue(ot._is_site_root("https://www.ahjg.com/"))
        self.assertTrue(ot._is_site_root("https://czju.suzhou.gov.cn/zfcg/"))
        self.assertFalse(ot._is_site_root(
            "https://www.wzbank.cn/purchase_info/view/page_id/36919"))

    def test_next_page_link_three_forms(self):
        # ① 文本「下一页」
        self.assertEqual(
            ot._next_page_link([{"t": "下一页", "h": "https://a.com/list?page=2"}], "https://a.com/list"),
            "https://a.com/list?page=2")
        # ② ?page=N
        self.assertEqual(
            ot._next_page_link([{"t": "2", "h": "https://a.com/list?page=2"}], "https://a.com/list"),
            "https://a.com/list?page=2")
        # ③ 路径分页（温州银行形态：只有 [1][2]…[10]，没有「下一页」也没有 ?page=）
        links = [{"t": f"[{i}]", "h": f"https://www.wzbank.cn/purchase_info/list/page/{i}"}
                 for i in range(1, 11)]
        self.assertEqual(
            ot._next_page_link(links, "https://www.wzbank.cn/purchase_info/list"),
            "https://www.wzbank.cn/purchase_info/list/page/2")
        self.assertEqual(
            ot._next_page_link(links, "https://www.wzbank.cn/purchase_info/list/page/3"),
            "https://www.wzbank.cn/purchase_info/list/page/4")

    def test_passed_target_date(self):
        # 列表按时间倒序：本页最新日期都早于目标 → 目标只可能更靠前，已经翻过头
        page = "公告一 2026年9月9日 公告二 2026年9月7日"
        self.assertFalse(ot._passed_target_date(page, "2026-08-28"))   # 目标更旧，还要继续翻
        self.assertTrue(ot._passed_target_date(page, "2026-10-01"))    # 目标更新，早该在前面出现
        self.assertFalse(ot._passed_target_date("没有日期", "2026-08-28"))

    def test_self_published_email(self):
        text = "项目联系人：傅女士 邮箱：07077@wzbank.cn"
        self.assertEqual(ot.self_published_email(text, "www.wzbank.cn"), ["wzbank.cn"])
        self.assertEqual(ot.self_published_email("邮箱：a@other.com", "www.wzbank.cn"), [])

    def test_extract_links_keeps_long_label(self):
        # 阶段词常在标题末尾，截断会把「招标公告」切掉 → 阶段比对失效
        html = '<html><body><a href="/x/1">温州银行股份有限公司关于杭州大楼绿植租摆养护服务项目采购公开招标公告</a></body></html>'
        links = ot.extract_links(html, "https://www.wzbank.cn/")
        self.assertEqual(len(links), 1)
        self.assertTrue(links[0]["t"].endswith("公开招标公告"))
        self.assertEqual(links[0]["h"], "https://www.wzbank.cn/x/1")

    def test_hard_hit_survives_punctuation(self):
        """标题里的「、（）」被 project_core 剥掉后，仍要在页面原文里匹配上（安徽交控实测）。"""
        title = "2026年度安徽交控生态科技有限公司花卉绿植租赁、养管服务采购（三次）项目询价公告"
        text = "2026年度安徽交控生态科技有限公司花卉绿植租赁、养管服务采购（三次）项目询价公告 正文如下"
        got = ot._fetch_and_verify(
            "https://www.ahjg.com/display.php?id=1", title=title, hints={"buyer": "安徽交控"},
            publish_date=None, portal_id="origin", wait_sec=0, download=False, min_score=0.5,
            fetch_fn=lambda url, **_: {"ok": True, "error": None, "summary": text[:400], "text": text,
                                       "pageTitle": title, "attachments": [], "session": "s"})
        self.assertTrue(got["hardHit"])

    def test_candidate_dedupe_keeps_different_ports(self):
        """端口必须参与去重：温州银行采购栏目在 :8087，被 80 端口主站 URL 挤掉过。"""
        results = [
            {"title": "温州银行", "url": "https://www.wzbank.cn/"},
            {"title": "温州银行采购信息", "url": "https://www.wzbank.cn:8087/purchase_info/list"},
        ]
        cands = ot._candidate_filter(results, registry=load_registry())
        netlocs = {c["url"] for c in cands}
        self.assertEqual(len(netlocs), 2)


if __name__ == "__main__":
    unittest.main()
