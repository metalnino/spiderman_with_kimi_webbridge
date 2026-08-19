"""WebBridge 一键运维入口 —— 打开/查看/关闭桥（幂等，零安装）。

用法:
  python scripts/wb_bridge.py status   # 桥与扩展连接状态
  python scripts/wb_bridge.py start    # 起桥服务 + 开浏览器 + 等扩展连上（缺啥补啥）
  python scripts/wb_bridge.py stop     # 停桥服务（读 pidfile）
  python scripts/wb_bridge.py wait     # 只等扩展连上（不主动起进程）

采集员（crawl/collector_employee.py）跑 webbridge 源前会自动调用 ensure_bridge()，
日常无需手工执行本脚本；本脚本供排障/手动运维用。
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crawl import webbridge_client as wb  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="WebBridge 一键运维")
    ap.add_argument("cmd", choices=["status", "start", "stop", "wait"])
    ap.add_argument("--wait-sec", type=float, default=90.0)
    args = ap.parse_args()

    if args.cmd == "status":
        st = wb._bridge_status()
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0 if st["up"] else 1

    if args.cmd == "start":
        res = wb.ensure_bridge(wait_sec=args.wait_sec)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0 if res["bridge"] else 1

    if args.cmd == "wait":
        import time
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
