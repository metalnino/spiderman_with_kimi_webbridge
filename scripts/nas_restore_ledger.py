"""恢复 NAS ledger 展示容器（采集关闭：CRAWL_CRON_HOURS=off），Web 8765 恢复。"""
from __future__ import annotations

from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
REMOTE_DIR = "/volume1/docker/spiderman"


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

    mode = 0o755
    size = local.stat().st_size
    chan.send(f"C{mode:04o} {size} {local.name}\n".encode())
    check()
    with open(local, "rb") as f:
        chan.sendall(f.read())
    chan.send(b"\x00")
    check()
    chan.close()


def main() -> None:
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(env("NAS_SSH_HOST"), port=int(env("NAS_SSH_PORT")),
                username=env("NAS_SSH_USER"), password=env("NAS_SSH_PASS"), timeout=25)
    pw = env("NAS_SSH_PASS")
    print("CONNECTED", flush=True)

    # 1) 上传新版 entrypoint（支持 CRAWL_CRON_HOURS=off → 只跑 ledger）
    scp_put(cli, ROOT / "scripts" / "docker_entrypoint.sh",
            f"{REMOTE_DIR}/scripts/docker_entrypoint.sh")
    print("UPLOADED docker_entrypoint.sh", flush=True)

    # 2) 改 compose：CRAWL_CRON_HOURS: "off"
    sed = (
        "sed -i 's/CRAWL_CRON_HOURS: \"8,12,18,22\"/CRAWL_CRON_HOURS: \"off\"/' "
        f"{REMOTE_DIR}/docker-compose.yml"
    )
    stdin, stdout, stderr = cli.exec_command(sed, timeout=60)
    stdout.channel.recv_exit_status()
    stdin, stdout, stderr = cli.exec_command(f"grep -n CRAWL {REMOTE_DIR}/docker-compose.yml", timeout=60)
    print("COMPOSE CRAWL LINES:\n", stdout.read().decode("utf-8", "ignore"), flush=True)

    # 3) 重建并启动（sudo）
    stdin, stdout, stderr = cli.exec_command(
        f"sudo -S -p '' sh -c 'cd {REMOTE_DIR} && /usr/local/bin/docker-compose up -d --build 2>&1 | tail -20'",
        get_pty=True, timeout=900,
    )
    stdin.write(pw + "\n")
    stdin.flush()
    print("=== UP BUILD ===\n", stdout.read().decode("utf-8", "ignore")[-1500:], flush=True)

    # 4) 复核：容器状态 + entry 日志 + 8765 health
    stdin, stdout, stderr = cli.exec_command(
        f"sudo -S -p '' sh -c '/usr/local/bin/docker ps --format \"{{.Names}}|{{.Status}}\" | head -5 && /usr/local/bin/docker logs spiderman_ledger --tail 15 2>&1'",
        get_pty=True, timeout=60,
    )
    stdin.write(pw + "\n")
    stdin.flush()
    print("=== PS+LOGS ===\n", stdout.read().decode("utf-8", "ignore")[:1200], flush=True)

    stdin, stdout, stderr = cli.exec_command("curl -s -m 8 http://127.0.0.1:8765/api/health || echo HEALTH_FAIL", timeout=30)
    print("=== HEALTH ===\n", stdout.read().decode("utf-8", "ignore")[:300], flush=True)
    cli.close()
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
