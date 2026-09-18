"""采集员入口「启动自记录」单测 —— 不需要外网 / DB / 邮件。

回归目标：Windows 任务 SpidermanCollector 的动作是裸 `python.exe scripts\\collector_run.py`，
Task Scheduler 不落 stdout，其 Operational 日志在本机也是关闭的（IsEnabled=False）。
2026-09-18 22:00 那轮就在启动数秒内死掉：Task 结果码 1、crawl_runs 零行、
reports/handoffs 全停在 12:40、无崩溃事件 —— 事后完全无法定位。
因此入口必须在任何「重」导入之前把 stdout/stderr 落盘并写启动戳。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "collector_run.py"


def _env(log_dir: Path, **extra) -> dict:
    env = dict(os.environ)
    env["SPIDER_LOG_DIR"] = str(log_dir)
    env["SPIDER_NO_EMAIL"] = "1"
    env.pop("SPIDER_NO_RUN_LOG", None)
    env.update({k: str(v) for k, v in extra.items()})
    return env


def _run(args, env, timeout=180):
    return subprocess.run(
        [sys.executable, *args],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


class TestRunLogBootstrap(unittest.TestCase):
    def test_help_run_writes_log_and_launch_stamp(self):
        with tempfile.TemporaryDirectory() as td:
            log_dir = Path(td) / "logs"
            proc = _run([str(SCRIPT), "--help"], _env(log_dir))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            logs = list(log_dir.glob("collector_run_*.log"))
            self.assertEqual(len(logs), 1)
            body = logs[0].read_text(encoding="utf-8")
            self.assertIn("usage:", body)
            self.assertIn("[collector_run] start", body)
            stamp = json.loads((log_dir / "collector_launch.json").read_text(encoding="utf-8"))
            self.assertEqual(stamp["logFile"], logs[0].name)
            self.assertEqual(stamp["argv"], ["--help"])
            self.assertEqual(stamp["executable"], sys.executable)
            self.assertTrue(stamp["cwd"])
            self.assertTrue(stamp["pid"])

    def test_disabled_by_env(self):
        with tempfile.TemporaryDirectory() as td:
            log_dir = Path(td) / "logs"
            proc = _run([str(SCRIPT), "--help"], _env(log_dir, SPIDER_NO_RUN_LOG="1"))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(list(log_dir.glob("collector_run_*.log")), [])
            self.assertFalse((log_dir / "collector_launch.json").exists())

    def test_import_has_no_side_effect(self):
        """被 import（tests/test_pipeline.py 就是这么加载的）时不得抢 stdout、不得建日志。"""
        with tempfile.TemporaryDirectory() as td:
            log_dir = Path(td) / "logs"
            original_out = sys.stdout
            os.environ["SPIDER_LOG_DIR"] = str(log_dir)
            try:
                spec = importlib.util.spec_from_file_location("collector_run_sideeffect_probe", SCRIPT)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            finally:
                os.environ.pop("SPIDER_LOG_DIR", None)
            self.assertIs(sys.stdout, original_out)
            self.assertFalse(log_dir.exists())
            # 重导入仍在模块层完成，契约名不变
            self.assertEqual(mod.IMPLEMENTS, "collector/v1.2.0")
            self.assertTrue(callable(mod.main))
            self.assertTrue(callable(mod._write_handoff))

    def test_retention_keeps_latest_30(self):
        with tempfile.TemporaryDirectory() as td:
            log_dir = Path(td) / "logs"
            log_dir.mkdir(parents=True)
            for i in range(35):
                (log_dir / f"collector_run_19990101_{i:06d}.log").write_text("old", encoding="utf-8")
            proc = _run([str(SCRIPT), "--help"], _env(log_dir))
            self.assertEqual(proc.returncode, 0, proc.stderr)
            logs = sorted(log_dir.glob("collector_run_*.log"))
            self.assertEqual(len(logs), 30)
            dummies = [p for p in logs if p.read_text(encoding="utf-8") == "old"]
            self.assertEqual(len(dummies), 29)
            self.assertIn("usage:", logs[-1].read_text(encoding="utf-8"))


class TestCrashIsRecorded(unittest.TestCase):
    """启动期/运行期暴死必须留栈 + 明确退出码 1（22:00 黑盒的直接修复）。"""

    def test_uncaught_exception_is_logged_with_traceback(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            log_dir = td / "logs"
            blocker = td / "blocker"
            blocker.write_text("not a directory", encoding="utf-8")  # 让 HANDOFF_DIR.mkdir 必失败
            driver = td / "driver.py"
            driver.write_text(
                textwrap.dedent(
                    f"""
                    import runpy, sys
                    sys.path.insert(0, {str(ROOT)!r})
                    import crawl.collector_employee as ce
                    # 不碰外网：直接把采集结果伪造成空跑，专注验证「异常留证」链路
                    ce.run = lambda *a, **k: {{
                        "output": [],
                        "report": {{"runId": "collector-testcrash"}},
                        "reportPath": "x",
                    }}
                    runpy.run_path({str(SCRIPT)!r}, run_name="__main__")
                    """
                ).strip(),
                encoding="utf-8",
            )
            env = _env(log_dir, SPIDER_HANDOFF_DIR=blocker / "sub")
            proc = _run([str(driver)], env)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            logs = list(log_dir.glob("collector_run_*.log"))
            self.assertEqual(len(logs), 1)
            body = logs[0].read_text(encoding="utf-8")
            self.assertIn("Traceback", body)
            self.assertIn("Error", body)
            self.assertIn("[collector_run] FATAL", body)
            self.assertTrue((log_dir / "collector_launch.json").exists())


if __name__ == "__main__":
    unittest.main()
