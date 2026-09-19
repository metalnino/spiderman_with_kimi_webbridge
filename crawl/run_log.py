"""运行时自记录（run log）—— 把进程输出落盘，死亡留证。入口与保活共用。

为什么需要（第一性）：观测必须自带持久化，不能依赖调用方重定向。
本机任务的动作是裸 `python.exe scripts\\collector_run.py` / `... wb_bridge.py watch`：
Task Scheduler 既不落 stdout（其 Operational 日志在本机也是 IsEnabled=False），
`ensure_daemon` 拉起保活时还把子进程 stdout/stderr 指向 DEVNULL。
于是「进程在启动或运行期死掉」就完全没有痕迹 —— 两次实证：
  - 2026-09-18 22:00 采集员：Task 结果码 1、crawl_runs 零行、无产物、无崩溃事件；
  - 2026-09-19 00:38 保活进程：心跳停更、桥随后掉线，同样查不到任何原因。

用法（三步）：
    handle = run_log.open_log(path, rotate_bytes=...)   # 打不开返回 None，绝不挡主流程
    run_log.install(handle)                             # 保留原流，同时写文件 + faulthandler
    run_log.prune(dir, "collector_run_*.log", keep=30)  # 可选：只保留最近 N 份
"""
from __future__ import annotations

import faulthandler
import sys
from pathlib import Path


class Tee:
    """把写往原流的每个 chunk 同时写进日志文件（原流可能被 DEVNULL 或任务调度器丢弃）。"""

    def __init__(self, *streams):
        self._streams = streams

    def write(self, text):
        for stream in self._streams:
            try:
                stream.write(text)
            except Exception:  # noqa: BLE001 —— 观测流绝不反噬主流程
                pass
        return len(text)

    def flush(self):
        for stream in self._streams:
            try:
                stream.flush()
            except Exception:  # noqa: BLE001
                pass

    def isatty(self):
        return False

    def reconfigure(self, **kwargs):
        return None

    @property
    def encoding(self):
        return "utf-8"

    @property
    def errors(self):
        return "replace"


def open_log(path, *, rotate_bytes: int | None = None):
    """打开（必要时先轮转）日志文件。任何失败返回 None —— 日志装不上绝不挡主流程。

    行缓冲（buffering=1）：进程被强杀时，已写出的行仍在文件里。
    """
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if rotate_bytes and p.exists() and p.stat().st_size > rotate_bytes:
            p.replace(p.with_name(p.name + ".1"))
        return open(p, "a", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        return None


def install(handle, *, fault_handler: bool = True) -> None:
    """把当前进程 stdout/stderr 接到 handle（保留原流）；可选开 faulthandler 抓硬崩栈。"""
    if handle is None:
        return
    if fault_handler:
        try:
            faulthandler.enable(handle)
        except Exception:  # noqa: BLE001
            pass
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        if stream is None:
            # 无控制台（pythonw / 分离启动 / WMI 拉起）时 sys.stdout 就是 None，
            # 不接管的话后面每个 print 都会炸 —— 直接让日志文件顶上。
            setattr(sys, name, Tee(handle))
            continue
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass
        setattr(sys, name, Tee(stream, handle))


def prune(directory, pattern: str, keep: int) -> None:
    """只保留最近 keep 份匹配文件（按文件名排序，时间戳命名即为时间序）。"""
    try:
        files = sorted(Path(directory).glob(pattern))
        for old in files[:-keep]:
            try:
                old.unlink()
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass
