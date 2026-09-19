"""WebBridge 一键运维入口 —— 打开/查看/关闭/保活（幂等，零安装）。

用法:
  python scripts/wb_bridge.py status        # 桥与扩展连接状态
  python scripts/wb_bridge.py start         # 起桥服务 + 开浏览器 + 等扩展连上（缺啥补啥，一次性）
  python scripts/wb_bridge.py stop          # 停桥服务（读 pidfile）
  python scripts/wb_bridge.py wait          # 只等扩展连上（不主动起进程）
  python scripts/wb_bridge.py watch         # 常驻保活：每 N 秒巡检，桥/扩展掉了自动拉起（单例）
  python scripts/wb_bridge.py ensure-daemon # 确保保活进程在跑（心跳判断；不在就后台拉起）

保活设计（"wb 不应该出现挂掉的状态"）：
  - **常驻 `watch`** 负责细粒度自愈（默认每 120s 巡检，掉了就 ensure_bridge 拉起），
    每轮写心跳 `data/web/wb_watch_heartbeat.json`；单次巡检异常绝不杀死保活。
  - **`ensure-daemon`** 解决"守护者自己挂了没人管"：任何需要桥的地方（采集员、登录自启任务）
    调用它即可——心跳新鲜则 no-op，心跳陈旧则后台重新拉起一个 watch（单例）。
  - 采集员侧另有 `_wait_bridge_ready()`（crawl/collector_employee.py）：采集时桥掉线会等它恢复。

采集员（crawl/collector_employee.py）跑 webbridge 源前会自动 ensure_bridge()，日常无需手工执行本脚本。
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crawl import run_log  # noqa: E402

WATCH_HEARTBEAT = ROOT / "data" / "web" / "wb_watch_heartbeat.json"
LOG_DIR = Path(os.environ.get("SPIDER_LOG_DIR") or (ROOT / "logs"))
WATCH_LOG = LOG_DIR / "wb_watch.log"
WATCH_LOG_HANDLES: list = []


def _install_watch_log() -> None:
    """保活自记录：它自己是「wb 不该挂」的执行者，但被 DEVNULL 掉就同样是黑盒。

    实证 2026-09-19 00:38：心跳停更、桥随后掉线，System/Application 事件日志一条都没有，
    连「保活什么时候死的」都查不出来。日志与心跳文件同源，任何失败都不挡保活。
    """
    if os.environ.get("SPIDER_NO_RUN_LOG") == "1":
        return
    handle = run_log.open_log(WATCH_LOG, rotate_bytes=2 * 1024 * 1024)
    if handle is None:
        return
    WATCH_LOG_HANDLES.append(handle)
    run_log.install(handle)
    print(f"[wb_watch] start {datetime.now():%Y-%m-%d %H:%M:%S} pid={os.getpid()} argv={sys.argv[1:]}", flush=True)


# 只有 watch 模式（常驻保活）才装日志，且必须在下面的重导入之前就位。
if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "watch":
    _install_watch_log()

from crawl import webbridge_client as wb  # noqa: E402


def watch_alive(max_age: float = 300.0) -> bool:
    """常驻保活是否在跑：以心跳新鲜度判断（跨平台，不用 os.kill 探测，避免误杀）。"""
    if not WATCH_HEARTBEAT.exists():
        return False
    try:
        d = json.loads(WATCH_HEARTBEAT.read_text(encoding="utf-8"))
        return (time.time() - float(d.get("ts") or 0)) <= max_age
    except Exception:  # noqa: BLE001
        return False


def _heartbeat(interval: float, bridge_ok: bool) -> None:
    try:
        WATCH_HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        WATCH_HEARTBEAT.write_text(
            json.dumps({"ts": time.time(), "pid": os.getpid(), "interval_s": interval, "bridge_ok": bridge_ok},
                       ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass


def ensure_daemon(*, interval: float = 120.0, stale_after: float = 300.0) -> dict:
    """确保常驻保活进程在跑（单例）：心跳新鲜 → no-op；否则后台 detached 拉起一个 watch。

    这是"守护者的守护者"问题的解：不依赖改任务触发器（需要提权），
    任何调用点都能把死掉的保活重新拉起来。
    """
    if watch_alive(stale_after):
        return {"started": False, "reason": "watch_alive"}
    import subprocess

    kwargs: dict = {}
    if hasattr(subprocess, "DETACHED_PROCESS"):
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS
    try:
        p = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "watch", "--interval", str(interval)],
            # 子进程自己装日志（见 _install_watch_log），这里不重定向到同一文件，避免重复行
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=str(ROOT), **kwargs,
        )
    except Exception as e:  # noqa: BLE001
        return {"started": False, "error": str(e)[:160]}
    return {"started": True, "pid": p.pid}


def main() -> int:
    ap = argparse.ArgumentParser(description="WebBridge 一键运维")
    ap.add_argument("cmd", choices=["status", "start", "stop", "wait", "watch", "ensure-daemon"])
    ap.add_argument("--wait-sec", type=float, default=90.0)
    ap.add_argument("--interval", type=float, default=120.0, help="watch 模式巡检间隔（秒）")
    args = ap.parse_args()

    if args.cmd == "watch":
        # 常驻保活：桥/扩展掉了就自动拉起来（"wb 不应该出现挂掉的状态"）
        from datetime import datetime

        interval = max(15.0, float(args.interval))
        if watch_alive(interval * 2):
            # 单例：已有新鲜心跳 → 保活已在跑，直接退出（避免重复保活）
            print(json.dumps({"watch": "already_running"}, ensure_ascii=False), flush=True)
            return 0
        print(json.dumps({"watch": "start", "interval_s": interval, "pid": os.getpid()}, ensure_ascii=False), flush=True)
        while True:
            bridge_ok = False
            try:
                st = wb._bridge_status()
                bridge_ok = bool(st.get("up")) and int(st.get("extensions") or 0) >= 1
                if not bridge_ok:
                    try:
                        res = wb.ensure_bridge(wait_sec=args.wait_sec)
                    except Exception as e:  # noqa: BLE001
                        res = {"bridge": False, "extensions": 0, "error": str(e)[:160]}
                    print(json.dumps({"t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                      "before": st, "ensure": res}, ensure_ascii=False), flush=True)
                    bridge_ok = bool(res.get("bridge")) and int(res.get("extensions") or 0) >= 1
            except Exception as e:  # noqa: BLE001 —— 单次巡检异常绝不能杀死保活
                print(json.dumps({"t": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                  "error": str(e)[:200]}, ensure_ascii=False), flush=True)
            _heartbeat(interval, bridge_ok)
            time.sleep(interval)

    if args.cmd == "ensure-daemon":
        print(json.dumps(ensure_daemon(interval=args.interval,
                                       stale_after=max(120.0, float(args.interval) * 2.5)),
                         ensure_ascii=False))
        return 0

    if args.cmd == "status":
        st = wb._bridge_status()
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0 if st["up"] else 1

    if args.cmd == "start":
        res = wb.ensure_bridge(wait_sec=args.wait_sec)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["bridge"] else 1

    if args.cmd == "wait":
        deadline = time.time() + args.wait_sec
        while time.time() < deadline and wb._bridge_status()["extensions"] < 1:
            time.sleep(3)
        st = wb._bridge_status()
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0 if st["up"] else 1

    if args.cmd == "stop":
        pidfile = ROOT / "data" / "web" / "webbridge_server.pid"
        if pidfile.exists():
            try:
                pid = int(pidfile.read_text(encoding="utf-8").strip())
                os.kill(pid, signal.SIGTERM)
                print(json.dumps({"stopped": True, "pid": pid}, ensure_ascii=False))
                pidfile.unlink(missing_ok=True)
                return 0
            except Exception as e:  # noqa: BLE001
                print(json.dumps({"stopped": False, "error": str(e)}, ensure_ascii=False))
                return 1
        # 无 pidfile：按端口找监听进程停（Windows 用 netstat+taskkill）
        print(json.dumps({"stopped": False, "error": "no_pidfile_use_taskkill_by_port_10086"}, ensure_ascii=False))
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
