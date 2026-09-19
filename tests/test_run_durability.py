"""采集与会话的「死亡不留黑洞」单测（全离线，不碰外网/DB/真浏览器）。

覆盖 2026-09-19 那次事故暴露的三处真实缺陷：
  1. 桥爬虫把 upsert 放在整个词循环之后 —— 进程被外部强杀时，已采的 29 个词一条都没入库；
  2. 进程被杀后 finish_run 不执行，crawl_runs 行永久停在 running（台账看着像「卡死」）；
  3. 保活进程（wb_bridge.py watch）的 stdout/stderr 被 DEVNULL 掉 —— 它自己死了也无痕。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _notice(nid: str, title: str = "某单位绿植租摆服务"):
    from crawl.models import Notice

    return Notice(source_id="jiangsu_zhaobiao", source_name="江苏招标网", title=title, external_id=nid)


def _load(module_name: str, relative: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / relative)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestRunLogPrimitives(unittest.TestCase):
    def test_tee_writes_to_all_streams(self):
        from crawl import run_log

        a, b = mock.MagicMock(), mock.MagicMock()
        tee = run_log.Tee(a, b)
        self.assertEqual(tee.write("x"), 1)
        a.write.assert_called_once_with("x")
        b.write.assert_called_once_with("x")
        tee.flush()
        self.assertFalse(tee.isatty())

    def test_tee_survives_broken_stream(self):
        """日志流坏了也绝不能反噬主流程（写原流照常）。"""
        from crawl import run_log

        good = mock.MagicMock()
        bad = mock.MagicMock()
        bad.write.side_effect = OSError("disk full")
        run_log.Tee(good, bad).write("y")
        good.write.assert_called_once_with("y")

    def test_open_log_creates_parents_and_rotates(self):
        from crawl import run_log

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "deep" / "nested" / "run.log"
            handle = run_log.open_log(path, rotate_bytes=10)
            self.assertIsNotNone(handle)
            handle.write("hello")
            handle.close()
            self.assertTrue(path.exists())

            # 超过 rotate_bytes → 轮转为 .1，新建空文件
            handle = run_log.open_log(path, rotate_bytes=1)
            handle.close()
            self.assertTrue((path.parent / "run.log.1").exists())

    def test_open_log_failure_returns_none(self):
        """打不开日志返回 None，绝不抛（观测不能挡住主流程）。"""
        from crawl import run_log

        with tempfile.TemporaryDirectory() as td:
            blocker = Path(td) / "afile"
            blocker.write_text("x", encoding="utf-8")
            self.assertIsNone(run_log.open_log(blocker / "sub" / "run.log"))

    def test_install_none_is_noop(self):
        from crawl import run_log

        original = sys.stdout
        run_log.install(None)
        self.assertIs(sys.stdout, original)

    def test_prune_keeps_newest(self):
        from crawl import run_log

        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for i in range(5):
                (d / f"collector_run_19990101_{i:06d}.log").write_text("x", encoding="utf-8")
            run_log.prune(d, "collector_run_*.log", 2)
            self.assertEqual(len(list(d.glob("collector_run_*.log"))), 2)


class TestJiangsuIncrementalUpsert(unittest.TestCase):
    """桥爬虫必须「逐词入库」：中途被杀也要留下已采部分，且如实报 partial。"""

    KW = ["绿植租摆", "花卉租摆", "办公绿化"]

    def _patch(self, js):
        return [
            mock.patch.object(js.wb, "available", return_value=True),
            mock.patch.object(js.wb, "navigate", return_value={"ok": True}),
            mock.patch.object(js.wb, "evaluate", return_value={"ok": True}),
            mock.patch.object(js.wb, "close_group", return_value=0),
            mock.patch.object(js, "human_pause", return_value=None),
            mock.patch.object(js, "wait_results", return_value=[{"any": "raw"}]),
            mock.patch.object(js, "start_run", return_value=739),
        ]

    def test_upserts_each_keyword_then_backstops(self):
        from scripts import crawl_jiangsu_wb as js

        upserts: list[int] = []

        def fake_upsert(notices):
            upserts.append(len(list(notices)))
            return {"attempted": len(list(notices)), "affected": len(list(notices))}

        fin = mock.MagicMock()
        patches = self._patch(js)
        patches += [
            mock.patch.object(js, "parse_items", side_effect=lambda raw, kw: [_notice(kw + "-1"), _notice(kw + "-2")]),
            mock.patch.object(js, "upsert_notices", side_effect=fake_upsert),
            mock.patch.object(js, "finish_run", fin),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        res = js.main(self.KW)

        # 3 个词各增量一次（每次 2 条）+ 结尾幂等兜底一次（6 条）
        self.assertEqual(upserts, [2, 2, 2, 6])
        self.assertEqual(res["status"], "success")
        self.assertEqual(len(res["notices"]), 6)
        self.assertEqual(fin.call_args.kwargs["item_count"], 6)

    def test_abort_midloop_keeps_partial_and_reports_it(self):
        """第 3 个词抛异常（模拟进程外/桥断）：前 2 个词已入库，必须报 partial + 真实条数。"""
        from scripts import crawl_jiangsu_wb as js

        calls = {"n": 0}

        def flaky_parse(raw, kw):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("bridge_unavailable: no_extension")
            return [_notice(kw + "-1"), _notice(kw + "-2")]

        fin = mock.MagicMock()
        patches = self._patch(js)
        patches += [
            mock.patch.object(js, "parse_items", side_effect=flaky_parse),
            mock.patch.object(js, "upsert_notices", side_effect=lambda ns: {"attempted": len(list(ns)), "affected": 0}),
            mock.patch.object(js, "finish_run", fin),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        res = js.main(self.KW)

        self.assertEqual(res["status"], "partial")
        self.assertEqual(len(res["notices"]), 4)          # 前 2 个词的结果保留下来了
        self.assertEqual(fin.call_args.kwargs["status"], "partial")
        self.assertEqual(fin.call_args.kwargs["item_count"], 4)
        self.assertIn("incremental=4", fin.call_args.kwargs["note"])


class TestQianlimaIncrementalUpsert(unittest.TestCase):
    KW = ["绿植租摆", "花卉租摆", "办公绿化"]

    def test_upserts_each_keyword_then_backstops(self):
        from scripts import crawl_qianlima_wb as qlm

        upserts: list[int] = []
        fin = mock.MagicMock()
        patches = [
            mock.patch.object(qlm.wb, "available", return_value=True),
            mock.patch.object(qlm.wb, "navigate", return_value={"ok": True}),
            mock.patch.object(qlm.wb, "evaluate", return_value={"ok": True}),
            mock.patch.object(qlm.wb, "close_group", return_value=0),
            mock.patch.object(qlm, "human_pause", return_value=None),
            mock.patch.object(qlm, "start_run", return_value=740),
            mock.patch.object(qlm, "search_page", return_value={"any": "payload"}),
            mock.patch.object(qlm, "parse_payload",
                              side_effect=lambda data, kw: [_notice(kw + "-1"), _notice(kw + "-2")]),
            mock.patch.object(qlm, "_filter_notices", side_effect=lambda ns: (list(ns), 0)),
            mock.patch.object(qlm, "upsert_notices",
                              side_effect=lambda ns: (upserts.append(len(list(ns)))
                                                      or {"attempted": len(list(ns)), "affected": 0})),
            mock.patch.object(qlm, "finish_run", fin),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        res = qlm.main(self.KW)

        self.assertEqual(upserts, [2, 2, 2, 6])
        self.assertEqual(res["status"], "success")
        self.assertEqual(fin.call_args.kwargs["item_count"], 6)

    def test_final_backstop_failure_reports_partial(self):
        """结尾幂等兜底那条 upsert 失败（DB 抖动）：已增量的 6 条不得被报成 0。"""
        from scripts import crawl_qianlima_wb as qlm

        calls = {"n": 0}

        def flaky_upsert(ns):
            calls["n"] += 1
            if calls["n"] == 4:  # 第 4 次 = 结尾兜底
                raise RuntimeError("db down")
            return {"attempted": len(list(ns)), "affected": 0}

        fin = mock.MagicMock()
        patches = [
            mock.patch.object(qlm.wb, "available", return_value=True),
            mock.patch.object(qlm.wb, "navigate", return_value={"ok": True}),
            mock.patch.object(qlm.wb, "evaluate", return_value={"ok": True}),
            mock.patch.object(qlm.wb, "close_group", return_value=0),
            mock.patch.object(qlm, "human_pause", return_value=None),
            mock.patch.object(qlm, "start_run", return_value=740),
            mock.patch.object(qlm, "search_page", return_value={"any": "payload"}),
            mock.patch.object(qlm, "parse_payload",
                              side_effect=lambda data, kw: [_notice(kw + "-1"), _notice(kw + "-2")]),
            mock.patch.object(qlm, "_filter_notices", side_effect=lambda ns: (list(ns), 0)),
            mock.patch.object(qlm, "upsert_notices", side_effect=flaky_upsert),
            mock.patch.object(qlm, "finish_run", fin),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

        res = qlm.main(self.KW)

        self.assertEqual(res["status"], "partial")
        self.assertEqual(res["notices"].__len__(), 6)
        self.assertEqual(fin.call_args.kwargs["item_count"], 6)
        self.assertEqual(fin.call_args.kwargs["status"], "partial")


class TestSweepOrphanRuns(unittest.TestCase):
    def _fake_conn(self, rows):
        cur = mock.MagicMock()
        cur.fetchall.return_value = rows
        cm = mock.MagicMock()
        cm.__enter__.return_value = cur
        cm.__exit__.return_value = False
        conn = mock.MagicMock()
        conn.cursor.return_value = cm
        return conn, cur

    def test_marks_stale_running_rows(self):
        from crawl import db_store

        rows = [{"id": 739, "source_id": "jiangsu_zhaobiao", "started_at": "2026-09-19 00:31:14"}]
        conn, cur = self._fake_conn(rows)
        with mock.patch.object(db_store, "connect", return_value=conn):
            out = db_store.sweep_orphan_runs(max_age_hours=3)

        self.assertEqual(out, [{"id": 739, "source_id": "jiangsu_zhaobiao", "started_at": "2026-09-19 00:31:14"}])
        self.assertEqual(cur.execute.call_count, 2)
        select_sql, select_params = cur.execute.call_args_list[0][0]
        self.assertIn("status='running'", select_sql)
        self.assertEqual(len(select_params), 1)  # 只有一个 cutoff 参数
        update_sql, update_params = cur.execute.call_args_list[1][0]
        self.assertIn("WHERE id IN (%s)", update_sql)
        self.assertEqual(update_params[1], db_store.ORPHAN_NOTE)
        self.assertEqual(update_params[2:], (739,))
        conn.close.assert_called_once()

    def test_no_rows_means_no_update(self):
        from crawl import db_store

        conn, cur = self._fake_conn([])
        with mock.patch.object(db_store, "connect", return_value=conn):
            self.assertEqual(db_store.sweep_orphan_runs(), [])
        self.assertEqual(cur.execute.call_count, 1)  # 只 SELECT，不发 UPDATE


class TestWatchSelfLog(unittest.TestCase):
    """保活进程自己是「wb 不该挂」的执行者，绝不能是黑盒。"""

    def test_importing_watch_module_has_no_side_effect(self):
        with tempfile.TemporaryDirectory() as td:
            log_dir = Path(td) / "logs"
            os.environ["SPIDER_LOG_DIR"] = str(log_dir)
            original = sys.stdout
            try:
                mod = _load("wb_bridge_import_probe", "scripts/wb_bridge.py")
            finally:
                os.environ.pop("SPIDER_LOG_DIR", None)
            self.assertIs(sys.stdout, original)
            self.assertFalse(log_dir.exists())
            self.assertTrue(callable(mod._install_watch_log))

    def test_installer_writes_log_and_tees_stdout(self):
        with tempfile.TemporaryDirectory() as td:
            log_dir = Path(td) / "logs"
            os.environ["SPIDER_LOG_DIR"] = str(log_dir)
            original_out, original_err = sys.stdout, sys.stderr
            try:
                mod = _load("wb_bridge_log_probe", "scripts/wb_bridge.py")
                mod._install_watch_log()
                self.assertIsNot(sys.stdout, original_out)
                print("[wb_watch] probe line", flush=True)
                for handle in mod.WATCH_LOG_HANDLES:
                    handle.flush()
            finally:
                sys.stdout, sys.stderr = original_out, original_err
                for handle in mod.WATCH_LOG_HANDLES:  # 夹具自清理：Windows 上不关句柄会锁住临时目录
                    try:
                        handle.close()
                    except Exception:  # noqa: BLE001
                        pass
                mod.WATCH_LOG_HANDLES.clear()
                os.environ.pop("SPIDER_LOG_DIR", None)

            body = (log_dir / "wb_watch.log").read_text(encoding="utf-8")
            self.assertIn("[wb_watch] start", body)
            self.assertIn("[wb_watch] probe line", body)
            self.assertIn(str(os.getpid()), body)

    def test_rotates_when_large(self):
        with tempfile.TemporaryDirectory() as td:
            log_dir = Path(td) / "logs"
            log_dir.mkdir(parents=True)
            (log_dir / "wb_watch.log").write_text("x" * 100, encoding="utf-8")
            os.environ["SPIDER_LOG_DIR"] = str(log_dir)
            try:
                from crawl import run_log

                handle = run_log.open_log(log_dir / "wb_watch.log", rotate_bytes=10)
                handle.close()
            finally:
                os.environ.pop("SPIDER_LOG_DIR", None)
            self.assertTrue((log_dir / "wb_watch.log.1").exists())


if __name__ == "__main__":
    unittest.main()
