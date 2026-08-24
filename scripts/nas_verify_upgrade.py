"""NAS ledger 升级后复验：容器状态、日志、健康、页面内容。"""
from __future__ import annotations

import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "/volume1/docker/spiderman"


def env(key: str) -> str:
    val = None
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not val:
        raise SystemExit(f"missing env {key}")
    return val


HOST = env("NAS_SSH_HOST")
PORT = int(env("NAS_SSH_PORT"))
USER = env("NAS_SSH_USER")
PW = env("NAS_SSH_PASS")


def main() -> None:
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, port=PORT, username=USER, password=PW, timeout=25)
    print("CONNECTED", flush=True)

    def run(cmd: str, t: int = 60, sudo: bool = False) -> tuple[int, str]:
        if sudo:
            i, o, e = cli.exec_command(f"sudo -S -p '' sh -c '{cmd}'", get_pty=True, timeout=t)
            i.write(PW + "\n")
            i.flush()
        else:
            i, o, e = cli.exec_command(cmd, timeout=t)
        out = o.read().decode("utf-8", "ignore")
        err = e.read().decode("utf-8", "ignore")
        try:
            code = o.channel.recv_exit_status()
        except Exception:
            code = -1
        return code, (out + err).strip()

    for attempt in range(6):
        code, out = run("curl -s -m 8 http://127.0.0.1:8765/api/health || echo HEALTH_FAIL")
        print(f"HEALTH#{attempt}:", out[:200], flush=True)
        if "HEALTH_FAIL" not in out:
            break
        time.sleep(10)

    code, out = run("/usr/local/bin/docker ps | head -5", sudo=True)
    print("=== PS ===\n", out[:400], flush=True)

    code, out = run("/usr/local/bin/docker logs spiderman_ledger --tail 25 2>&1", sudo=True)
    print("=== LOGS ===\n", out[:1500], flush=True)

    code, out = run("curl -s -m 8 http://127.0.0.1:8765/ | grep -c lActionable; curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/")
    print("=== HTTP / ===", out[:100], sep="\n", flush=True)

    code, out = run("curl -s -m 8 'http://127.0.0.1:8765/api/leads?actionable=1&limit=3' | head -c 500")
    print("=== API actionable ===", out[:500], sep="\n", flush=True)

    code, out = run(f"grep -c lActionable {REMOTE}/data/web/ledger_app.html")
    print("=== NAS file lActionable ===", out[:100], sep="\n", flush=True)
    cli.close()
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
