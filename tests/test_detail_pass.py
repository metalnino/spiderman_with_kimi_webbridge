"""详情正文补全（crawl/detail_pass.py）单测 —— 全离线，不碰外网/DB。

回归目标：这条链此前**没有任何定时入口**（collector_detail.py 未接任务），
导致 3166 条里 3103 条 detail_status 为 null、只有 7 条落了附件正文。
这里锁住四件事：候选优先级与过滤口径、三重封顶（总数/每站/耗时）、
正文计数如实、以及 summary 不再被 200 字截断。
"""
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

from crawl import detail_pass as dp  # noqa: E402


def _fake_cursor(rows):
    cur = mock.MagicMock()
    cur.fetchall.return_value = rows
    cm = mock.MagicMock()
    cm.__enter__.return_value = cur
    cm.__exit__.return_value = False
    conn = mock.MagicMock()
    conn.cursor.return_value = cm
    return conn, cur


class TestPickCandidates(unittest.TestCase):
    def test_sql_priority_and_filters(self):
        conn, cur = _fake_cursor([])
        with mock.patch.object(dp, "connect", return_value=conn):
            dp.pick_candidates(
                limit_total=10, per_source_limit=2, min_summary_chars=400,
                exclude_sources=("cebpub", "rccchina"),
                retry_error_prefixes=("err:bridge", "err:detail_page"),
            )
        sql, params = cur.execute.call_args[0]
        # 只有「没试过」或「可自愈瞬时失败」才算候选：永久失败（验证码门/登录墙/无附件）不重打
        self.assertIn("detail_status IS NULL", sql)
        self.assertIn("err:bridge%", params)
        self.assertIn("err:detail_page%", params)
        self.assertNotIn("err:no_attachment_link%", params)
        self.assertNotIn("err:detail_vaptcha_gated%", params)
        # 可投标阶段优先 + 发布时间新→旧
        self.assertIn("CASE notice_stage", sql)
        self.assertIn("WHEN 'bidding' THEN 1", sql)
        self.assertIn("publish_date DESC", sql)
        # 排除人工门站点 + 摘要长度门槛 + 按站均衡取候选（窗口函数，避免前几站吃满上限后无槽位）
        self.assertIn("source_id NOT IN (%s,%s)", sql)
        self.assertIn("cebpub", params)
        self.assertIn(400, params)
        self.assertIn("ROW_NUMBER() OVER (PARTITION BY source_id", sql)
        self.assertIn("t.rn <= %s", sql)
        self.assertEqual(params[-2], 2)   # 每站上限
        self.assertGreaterEqual(params[-1], 10)  # 整体兜底 LIMIT
        conn.close.assert_called_once()

    def test_no_exclude_and_sources_filter(self):
        conn, cur = _fake_cursor([])
        with mock.patch.object(dp, "connect", return_value=conn):
            dp.pick_candidates(limit_total=3, per_source_limit=1, min_summary_chars=0,
                               sources=("ccgp", "ggzy"))
        sql, params = cur.execute.call_args[0]
        self.assertIn("source_id IN (%s,%s)", sql)
        self.assertNotIn("NOT IN", sql)
        self.assertEqual(params[-2], 1)          # 每站上限
        self.assertGreaterEqual(params[-1], 3)   # 整体兜底 LIMIT


class TestRunDetailPass(unittest.TestCase):
    def _cands(self, spec):
        return [{"id": i, "source_id": s, "title": f"{s}-{i}"} for i, s in spec]

    def test_counts_and_caps(self):
        cands = self._cands([(1, "ccgp"), (2, "ccgp"), (3, "ccgp"), (4, "ggzy"), (5, "ggzy")])
        calls: list = []

        def fake_backfill(nid):
            calls.append(nid)
            return {"ok": True, "summary": "x" * 500, "tenderfile_path": f"p/{nid}.docx"}

        stats = dp.run_detail_pass(
            limit_total=10, per_source_limit=2, max_seconds=0, min_summary_chars=400,
            use_ai=False, candidates_fn=lambda: cands, backfill_fn=fake_backfill,
        )
        self.assertEqual(calls, [1, 2, 4, 5])          # 每站封顶 2
        self.assertEqual(stats["processed"], 4)
        self.assertEqual(stats["detail_ok"], 4)
        self.assertEqual(stats["text_ok"], 4)          # tenderfile_path 才算「拿到正文」
        self.assertEqual(stats["summary_ok"], 4)
        self.assertEqual(stats["stopped_reason"], "candidates_exhausted")
        self.assertEqual(stats["per_source"]["ccgp"]["text_ok"], 2)
        self.assertEqual(len(stats["traces"]), 4)

    def test_total_cap_stops(self):
        cands = self._cands([(i, "ggzy") for i in range(1, 6)])
        calls: list = []
        stats = dp.run_detail_pass(
            limit_total=2, per_source_limit=99, max_seconds=0, min_summary_chars=0,
            use_ai=False, candidates_fn=lambda: cands,
            backfill_fn=lambda nid: (calls.append(nid), {"ok": True})[1],
        )
        self.assertEqual(calls, [1, 2])
        self.assertEqual(stats["stopped_reason"], "limit_total")

    def test_time_budget_is_deterministic(self):
        """jiangsu 单条实测可达 91s —— 必须有硬性耗时上限，超了立刻收手并如实记原因。"""
        cands = self._cands([(i, "jiangsu_zhaobiao") for i in range(1, 6)])
        clock = {"t": 1000.0}

        def fake_time():
            return clock["t"]

        def slow_backfill(nid):
            clock["t"] += 5.0
            return {"ok": True}

        with mock.patch.object(dp.time, "time", side_effect=fake_time):
            stats = dp.run_detail_pass(
                limit_total=10, per_source_limit=9, max_seconds=12, min_summary_chars=0,
                use_ai=False, candidates_fn=lambda: cands, backfill_fn=slow_backfill,
            )
        self.assertEqual(stats["processed"], 3)        # 1000→1005→1010 之后 1012 已到期
        self.assertEqual(stats["stopped_reason"], "time_budget")

    def test_failure_is_honest_and_not_fatal(self):
        cands = self._cands([(1, "ccgp")])

        def boom(nid):
            raise RuntimeError("network down")

        stats = dp.run_detail_pass(
            limit_total=5, per_source_limit=5, max_seconds=0, min_summary_chars=0,
            use_ai=False, candidates_fn=lambda: cands, backfill_fn=boom,
        )
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(stats["detail_ok"], 0)
        self.assertEqual(stats["text_ok"], 0)
        self.assertIn("RuntimeError", stats["errors"][0]["error"])

    def test_ai_only_when_enabled(self):
        cands = self._cands([(1, "ccgp"), (2, "ggzy")])
        ai_calls: list = []

        def fake_ai(nid):
            ai_calls.append(nid)
            return {"ok": True, "filled": ["buyer"]}

        base = dict(limit_total=5, per_source_limit=5, max_seconds=0, min_summary_chars=0,
                    candidates_fn=lambda: cands, backfill_fn=lambda nid: {"ok": True})
        off = dp.run_detail_pass(use_ai=False, ai_fn=fake_ai, **base)
        self.assertEqual(ai_calls, [])
        self.assertNotIn("ai", off["traces"][0])
        on = dp.run_detail_pass(use_ai=True, ai_fn=fake_ai, **base)
        self.assertEqual(ai_calls, [1, 2])
        self.assertEqual(on["ai_ok"], 2)
        self.assertEqual(on["traces"][0]["ai"]["filled"], ["buyer"])


class TestLoadCfg(unittest.TestCase):
    def test_defaults_from_config(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SPIDER_NO_DETAIL_PASS", None)
            os.environ.pop("SPIDER_DETAIL_AI", None)
            cfg = dp.load_cfg()
        self.assertTrue(cfg["enabled"])
        # 断言「量级合理」而不是钉死数字：配额会随运营调整（当前 80/10/900），
        # 但绝不能小到追不上新增（一轮新增约 300 条）或大到拖垮出勤。
        self.assertGreaterEqual(cfg["limit_total"], 40)
        self.assertGreaterEqual(cfg["per_source_limit"], 6)
        self.assertGreaterEqual(cfg["max_seconds"], 300)
        self.assertLessEqual(cfg["max_seconds"], 1800)
        self.assertIn("cebpub", cfg["exclude_sources"])   # 人工 vaptcha 门，默认不浪费预算

    def test_env_seams(self):
        with mock.patch.dict(os.environ, {
            "SPIDER_NO_DETAIL_PASS": "1", "SPIDER_DETAIL_AI": "1",
            "SPIDER_DETAIL_PASS_TOTAL": "7", "SPIDER_DETAIL_PASS_PER_SOURCE": "2",
            "SPIDER_DETAIL_PASS_MAX_SEC": "30",
        }):
            cfg = dp.load_cfg()
        self.assertFalse(cfg["enabled"])
        self.assertTrue(cfg["use_ai"])
        self.assertEqual((cfg["limit_total"], cfg["per_source_limit"], cfg["max_seconds"]), (7, 2, 30))

    def test_config_file_block_wins_over_defaults(self):
        blk = {"detail_pass": {"limit_total": 99, "exclude_sources": ["tgnet"]}}
        with mock.patch("crawl.config_loader.anti_bot_cfg", return_value=blk):
            cfg = dp.load_cfg()
        self.assertEqual(cfg["limit_total"], 99)
        self.assertEqual(cfg["exclude_sources"], ["tgnet"])


class TestSummaryCharsRaised(unittest.TestCase):
    def test_summary_no_longer_capped_at_200(self):
        """200 字等于没正文：jiangsu/yfbzb/chinabidding/qianlima/tgnet 实测全被截在 200。"""
        from crawl import tenderfile

        self.assertGreaterEqual(tenderfile.SUMMARY_CHARS, 1000)
        self.assertEqual(len(tenderfile._page_summary("<p>" + "绿" * 5000 + "</p>")),
                         tenderfile.SUMMARY_CHARS)


class TestCcpgAlsoFetchesAttachment(unittest.TestCase):
    """ccgp 走字段分支，原实现在字段抓完就 return —— 附件链从未执行，一条正文都没落过。"""

    def test_field_source_merges_tenderfile(self):
        from crawl import backfill as bf

        with mock.patch.object(bf, "_load_row", return_value={
                "id": 1, "source_id": "ccgp", "title": "某招标公告",
                "detail_url": "https://www.ccgp.gov.cn/a.htm", "official_url": None}), \
             mock.patch.object(bf, "fetch_detail", return_value={"buyer": "某单位", "summary": "短"}), \
             mock.patch.object(bf, "fetch_tenderfile", return_value={
                 "ok": True, "summary": "长" * 800,
                 "tenderFile": {"path": "downloads/tenderfiles/ccgp/x.pdf"}}), \
             mock.patch.object(bf, "_save_result") as save:
            r = bf.backfill_notice(1)
        self.assertTrue(r["ok"])
        self.assertEqual(r["tenderfile_path"], "downloads/tenderfiles/ccgp/x.pdf")
        self.assertEqual(len(r["summary"]), 800)          # 取更长的正文
        self.assertEqual(r["fields"], {"buyer": "某单位"})
        self.assertEqual(save.call_args.kwargs["tenderfile_path"], "downloads/tenderfiles/ccgp/x.pdf")
        self.assertEqual(save.call_args.kwargs["detail_status"], "ok")

    def test_field_source_without_attachment_still_ok(self):
        from crawl import backfill as bf

        with mock.patch.object(bf, "_load_row", return_value={
                "id": 2, "source_id": "ccgp", "title": "t",
                "detail_url": "https://www.ccgp.gov.cn/b.htm", "official_url": None}), \
             mock.patch.object(bf, "fetch_detail", return_value={"buyer": "某单位", "summary": "正文"}), \
             mock.patch.object(bf, "fetch_tenderfile", return_value={"ok": False, "error": "no_attachment_link"}), \
             mock.patch.object(bf, "_save_result") as save:
            r = bf.backfill_notice(2)
        self.assertTrue(r["ok"])
        self.assertIsNone(r["tenderfile_path"])
        self.assertEqual(save.call_args.kwargs["detail_status"], "ok")

    def test_field_source_total_failure_is_honest(self):
        from crawl import backfill as bf

        with mock.patch.object(bf, "_load_row", return_value={
                "id": 3, "source_id": "ccgp", "title": "t",
                "detail_url": "https://www.ccgp.gov.cn/c.htm", "official_url": None}), \
             mock.patch.object(bf, "fetch_detail", return_value={}), \
             mock.patch.object(bf, "fetch_tenderfile", return_value={"ok": False, "error": "detail_page_empty_or_blocked"}), \
             mock.patch.object(bf, "_save_result") as save:
            r = bf.backfill_notice(3)
        self.assertFalse(r["ok"])
        self.assertTrue(save.call_args.kwargs["detail_status"].startswith("err:"))


if __name__ == "__main__":
    unittest.main()
