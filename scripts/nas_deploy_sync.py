"""NAS ledger 升级部署（v2 全量同步）：本地打 tar → SCP → 备份 → 覆盖 → 关采集 → 重建重启 → 验收。"""
from __future__ import annotations

import io
import tarfile
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

INCLUDE = [
    "Dockerfile",
    "docker-compose.yml",
    ".dockerignore",
    ".env.example",
    "requirements.txt",
    "sql",
    "config",
    "crawl",
    "scripts",
    "data/web/ledger_app.html",
]

REMOTE_SH = """#!/bin/sh
set -e
tar -xzf /tmp/spiderman_deploy.tar.gz -C {d}
rm -f /tmp/spiderman_deploy.tar.gz
sed -i 's/CRAWL_CRON_HOURS: "8,12,18,22"/CRAWL_CRON_HOURS: "off"/' {d}/docker-compose.yml
echo '=== CRAWL LINES ==='
grep -n CRAWL {d}/docker-compose.yml
echo '=== UP BUILD ==='
cd {d} && /usr/local/bin/docker-compose up -d --build 2>&1 | tail -20
echo '=== PS ==='
/usr/local/bin/docker ps | head -6
echo '=== LOGS ==='
/usr/local/bin/docker logs spiderman_ledger --tail 8 2>&1
""".format(d=REMOTE)


def make_tar() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel in INCLUDE:
            p = ROOT / rel
            if not p.exists():
                continue
            if p.is_file():
                tar.add(p, arcname=rel)
            else:
                for f in p.rglob("*"):
                    if f.is_file() and "__pycache__" not in str(f) and ".pyc" not in f.name:
                        tar.add(f, arcname=f.relative_to(ROOT).as_posix())
    return buf.getvalue()


def scp_put(cli: paramiko.SSHClient, data: bytes, remote_path: str) -> None:
    chan = cli.get_transport().open_session()
    chan.exec_command(f"scp -t {remote_path}")

    def check() -> None:
        code = chan.recv(1)
        if code == b"\x00":
            return
        err = chan.recv(1024).decode("utf-8", "ignore")
        raise RuntimeError(f"scp remote error code={code!r} {err}")

    name = remote_path.rsplit("/", 1)[1]
    chan.send(f"C0644 {len(data)} {name}\n".encode())
    check()
    chan.sendall(data)
    chan.send(b"\x00")
    check()
    chan.close()


def main() -> None:
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(HOST, port=PORT, username=USER, password=PW, timeout=25)
    print("CONNECTED", flush=True)

    def run(cmd: str, t: int = 120, sudo: bool = False) -> tuple[int, str]:
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

    # 1) 打包
    data = make_tar()
    print(f"TAR_BYTES {len(data)}", flush=True)

    # 2) 备份旧目录
    ts = time.strftime("%Y%m%d%H%M%S")
    print("BACKUP:", run(f"tar -czf /tmp/spiderman_backup_{ts}.tar.gz -C /volume1/docker spiderman")[1][:200], flush=True)

    # 3) 上传 tar + 远程脚本
    scp_put(cli, data, "/tmp/spiderman_deploy.tar.gz")
    print("UPLOADED TAR", flush=True)
    scp_put(cli, REMOTE_SH.encode(), "/tmp/nas_upgrade.sh")
    print("UPLOADED SH", flush=True)

    # 4) sudo 执行远程脚本（解压→关采集→重建重启→状态）
    code, out = run("sh /tmp/nas_upgrade.sh", t=1200, sudo=True)
    print(f"=== REMOTE SCRIPT code={code} ===\n{out[-3500:]}", flush=True)

    # 5) 验收（非 sudo）
    code, out = run("curl -s -m 8 http://127.0.0.1:8765/api/health || echo HEALTH_FAIL")
    print("=== HEALTH ===\n", out[:300], flush=True)
    code, out = run(f"grep -c lActionable {REMOTE}/data/web/ledger_app.html")
    print("=== NAS ledger lActionable count ===\n", out[:100], flush=True)
    code, out = run("curl -s -m 8 http://127.0.0.1:8765/ | grep -c lActionable")
    print("=== HTTP / lActionable count ===\n", out[:100], flush=True)
    cli.close()
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
