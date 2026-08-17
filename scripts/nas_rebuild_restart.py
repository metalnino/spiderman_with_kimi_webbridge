"""NAS 重建+重启 v3：sudo -S 提权 docker。"""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]


def env(key: str) -> str:
    val = None
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
    return val


def main() -> None:
    pw = env("NAS_SSH_PASS")
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(env("NAS_SSH_HOST"), port=int(env("NAS_SSH_PORT")), username=env("NAS_SSH_USER"), password=pw, timeout=25)
    print("CONNECTED", flush=True)

    def run(cmd: str, timeout: int = 900, sudo: bool = False):
        if sudo:
            cmd = f"echo '{pw}' | sudo -S -p '' {cmd}"
        stdin, stdout, stderr = cli.exec_command(cmd, timeout=timeout, get_pty=True)
        out = stdout.read().decode("utf-8", "ignore")
        err = stderr.read().decode("utf-8", "ignore")
        code = stdout.channel.recv_exit_status()
        return code, (out + "\n" + err).strip()

    code, out = run("sudo -S -p '' /usr/local/bin/docker-compose version", sudo=False)
    # sudo 本身需要密码：改用交互式管道
    stdin, stdout, stderr = cli.exec_command("sudo -S -p '' /usr/local/bin/docker-compose version", get_pty=True)
    stdin.write(pw + "\n")
    stdin.flush()
    ver = stdout.read().decode("utf-8", "ignore")
    print("SUDO_VERSION:", ver[:200], flush=True)

    stdin, stdout, stderr = cli.exec_command(
        "cd /volume1/docker/spiderman && sudo -S -p '' /usr/local/bin/docker-compose up -d --build 2>&1 | tail -25",
        get_pty=True,
        timeout=900,
    )
    stdin.write(pw + "\n")
    stdin.flush()
    build_out = stdout.read().decode("utf-8", "ignore")
    print("BUILD:", build_out[-2500:], flush=True)

    stdin, stdout, stderr = cli.exec_command(
        "cd /volume1/docker/spiderman && sudo /usr/local/bin/docker-compose ps 2>&1", get_pty=True, timeout=60
    )
    stdin.write(pw + "\n")
    stdin.flush()
    ps_out = stdout.read().decode("utf-8", "ignore")
    print("PS:", ps_out[-800:], flush=True)
    cli.close()


if __name__ == "__main__":
    main()
