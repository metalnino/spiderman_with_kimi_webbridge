"""NAS SSH 部署（v2）：SFTP 不可用，走 legacy SCP 协议上传（等效 scp -O）。"""
from __future__ import annotations

import os
import stat as stat_mod
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]


def env(key: str) -> str:
    val = None
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not val:
        raise SystemExit(f"missing env {key}")
    return val


REMOTE_DIR = "/volume1/docker/spiderman"
UPLOAD_DIRS = ["crawl", "config"]
UPLOAD_FILES = ["scripts/crawl_ccgp_wb.py", ".cursor/docs/anti_bot_lessons.html", "tests/test_all.py"]


def scp_put(cli: paramiko.SSHClient, local: Path, remote_path: str) -> None:
    chan = cli.get_transport().open_session()
    chan.exec_command(f"scp -t {remote_path}")

    def check() -> None:
        code = chan.recv(1)
        if code == b"\x00":
            return
        err = chan.recv(1024).decode("utf-8", "ignore")
        raise RuntimeError(f"scp remote error code={code!r} {err}")

    mode = 0o644
    size = local.stat().st_size
    chan.send(f"C{mode:04o} {size} {local.name}\n".encode())
    check()
    with open(local, "rb") as f:
        chan.sendall(f.read())
    chan.send(b"\x00")
    check()
    chan.close()


def run(cli: paramiko.SSHClient, cmd: str, timeout: int = 180) -> tuple[int, str]:
    stdin, stdout, stderr = cli.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "ignore")
    err = stderr.read().decode("utf-8", "ignore")
    code = stdout.channel.recv_exit_status()
    return code, (out + "\n" + err).strip()


def main() -> None:
    host = env("NAS_SSH_HOST")
    port = int(env("NAS_SSH_PORT"))
    user = env("NAS_SSH_USER")
    pw = env("NAS_SSH_PASS")
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(host, port=port, username=user, password=pw, timeout=25)
    print("CONNECTED", host, port, flush=True)
    code, out = run(cli, f"ls {REMOTE_DIR} | head -30")
    print("REMOTE_LS code=", code, out[:600], flush=True)

    files: list[tuple[Path, str]] = []
    for d in UPLOAD_DIRS:
        for f in (ROOT / d).rglob("*"):
            if not f.is_file() or "__pycache__" in str(f) or f.name.endswith(".pyc"):
                continue
            rel = f.relative_to(ROOT).as_posix()
            files.append((f, f"{REMOTE_DIR}/{rel}"))
    for rel in UPLOAD_FILES:
        p = ROOT / rel
        if p.exists():
            files.append((p, f"{REMOTE_DIR}/{rel}"))

    for local, remote in files:
        parent = str(Path(remote).parent)
        run(cli, f"mkdir -p {parent}")
        try:
            scp_put(cli, local, remote)
            print("PUT", remote.replace(REMOTE_DIR + "/", ""), flush=True)
        except Exception as e:
            print("PUT_ERR", remote, str(e)[:200], flush=True)

    code, out = run(cli, f"cd {REMOTE_DIR} && head -45 docker-compose.yml")
    print("=== COMPOSE HEAD ===\n", out[:2500], flush=True)
    code, out = run(cli, "docker ps --format '{{.Names}} {{.Status}}' | head -10")
    print("=== DOCKER PS ===\n", out[:800], flush=True)
    cli.close()


if __name__ == "__main__":
    main()
