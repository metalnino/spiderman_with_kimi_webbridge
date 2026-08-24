"""NAS 单文件上传（SSH/SCP）+ 页面验证：升级 data/web/ledger_app.html。"""
from __future__ import annotations

from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
REMOTE = "/volume1/docker/spiderman"
REL = "data/web/ledger_app.html"


def env(key: str) -> str:
    val = None
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not val:
        raise SystemExit(f"missing env {key}")
    return val


def scp_put(cli: paramiko.SSHClient, local: Path, remote_path: str) -> None:
    chan = cli.get_transport().open_session()
    chan.exec_command(f"scp -t {remote_path}")

    def check() -> None:
        code = chan.recv(1)
        if code == b"\x00":
            return
        err = chan.recv(1024).decode("utf-8", "ignore")
        raise RuntimeError(f"scp remote error code={code!r} {err}")

    data = local.read_bytes().replace(b"\r\n", b"\n")
    chan.send(f"C0644 {len(data)} {local.name}\n".encode())
    check()
    chan.sendall(data)
    chan.send(b"\x00")
    check()
    chan.close()


def main() -> None:
    local = ROOT / REL
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(env("NAS_SSH_HOST"), port=int(env("NAS_SSH_PORT")),
                username=env("NAS_SSH_USER"), password=env("NAS_SSH_PASS"), timeout=25)
    print("CONNECTED", flush=True)

    scp_put(cli, local, f"{REMOTE}/{REL}")
    print("UPLOADED", flush=True)

    def run(cmd: str, t: int = 30) -> str:
        i, o, e = cli.exec_command(cmd, timeout=t)
        return (o.read().decode("utf-8", "ignore") + e.read().decode("utf-8", "ignore")).strip()

    print("NAS crawlNow count:", run(f"grep -c crawlNow {REMOTE}/{REL}"), flush=True)
    print("HTTP / crawlNow count:", run("curl -s -m 8 http://127.0.0.1:8765/ | grep -c crawlNow"), flush=True)
    print("HTTP code:", run("curl -s -m 8 -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/"), flush=True)
    print("HTTP / lActionable count:", run("curl -s -m 8 http://127.0.0.1:8765/ | grep -c lActionable"), flush=True)
    cli.close()
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
