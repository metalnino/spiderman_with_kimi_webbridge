"""NAS 台账升级：把本仓库最新代码同步到 NAS 展示容器并重建。

口径（2026-08-22 定稿）：采集=本机，展示=NAS 8765（同 MySQL）。
- 只上传运行台账所需的代码树 + 壳页（data/web 挂载目录，上传即生效）
- 不动远端 .env（NAS 自己的 MySQL 配置）与 docker-compose.yml（CRAWL_CRON_HOURS=off）
- 重建后自检：容器状态 / health / 壳页排序默认项 / API 默认发布时间倒序

用法：python scripts/nas_upgrade_ledger.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
REMOTE_DIR = "/volume1/docker/spiderman"

# 需要同步的目录（整目录递归，排除 __pycache__/pyc）
SYNC_DIRS = ["crawl", "scripts", "config", "sql"]
# 需要同步的单文件（相对仓库根）
SYNC_FILES = ["Dockerfile", ".dockerignore", ".env.example", "requirements.txt"]
# 壳页/静态页（远端 data/web 为容器挂载源，仅同步台账实际使用与快照页）
SYNC_WEB = ["ledger_app.html", "dashboard.html", "incremental.html", "crm.html"]
# 绝不覆盖的远端文件
PRESERVE = {".env", "docker-compose.yml"}


def env(key: str) -> str:
    val = None
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith(key + "="):
            val = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not val:
        raise SystemExit(f"missing env {key}")
    return val


def run(cli: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[int, str]:
    stdin, stdout, stderr = cli.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "ignore")
    err = stderr.read().decode("utf-8", "ignore")
    code = stdout.channel.recv_exit_status()
    return code, (out + "\n" + err).strip()


def sudo_run(cli: paramiko.SSHClient, cmd: str, pw: str, timeout: int = 900) -> tuple[int, str]:
    stdin, stdout, stderr = cli.exec_command(
        f"sudo -S -p '' {cmd}", get_pty=True, timeout=timeout
    )
    stdin.write(pw + "\n")
    stdin.flush()
    out = stdout.read().decode("utf-8", "ignore")
    code = stdout.channel.recv_exit_status()
    return code, out.strip()


def scp_put(cli: paramiko.SSHClient, local: Path, remote_path: str) -> None:
    """Synology SSH 未开 sftp 子系统，走 scp -t（nas_restore_ledger 同款）。"""
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


def _walk(local_dir: Path, remote_dir: str, cli: paramiko.SSHClient) -> list[str]:
    """上传整个目录（mkdir + scp），返回上传文件清单。"""
    uploaded: list[str] = []
    files = [
        p for p in sorted(local_dir.rglob("*"))
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    ]
    dirs = sorted({str(p.parent.relative_to(ROOT).as_posix()) for p in files})
    for d in dirs:
        run(cli, f"mkdir -p '{remote_dir}/{d}'")
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        scp_put(cli, p, f"{remote_dir}/{rel}")
        uploaded.append(rel)
    return uploaded


def main() -> None:
    host = env("NAS_SSH_HOST")
    port = int(env("NAS_SSH_PORT"))
    user = env("NAS_SSH_USER")
    pw = env("NAS_SSH_PASS")
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(host, port=port, username=user, password=pw, timeout=25)
    print("CONNECTED", host, flush=True)

    # ---- 1) 现状 ----
    code, out = sudo_run(cli, "/usr/local/bin/docker ps --format '{{.Names}}|{{.Status}}' | head -6", pw)
    print("=== BEFORE: DOCKER PS ===\n" + out[:500], flush=True)
    code, out = run(cli, f"grep -n CRAWL_CRON_HOURS {REMOTE_DIR}/docker-compose.yml")
    print("=== COMPOSE CRAWL ===\n" + out[:200], flush=True)

    # ---- 2) 上传 ----
    uploaded: list[str] = []
    for d in SYNC_DIRS:
        uploaded += _walk(ROOT / d, REMOTE_DIR, cli)
    for f in SYNC_FILES:
        run(cli, f"mkdir -p '{REMOTE_DIR}'")
        scp_put(cli, ROOT / f, f"{REMOTE_DIR}/{f}")
        uploaded.append(f)
    run(cli, f"mkdir -p '{REMOTE_DIR}/data/web'")
    for f in SYNC_WEB:
        scp_put(cli, ROOT / "data" / "web" / f, f"{REMOTE_DIR}/data/web/{f}")
        uploaded.append(f"data/web/{f}")
    print(f"UPLOADED {len(uploaded)} files", flush=True)
    print("sample:", ", ".join(uploaded[:8]), "...", flush=True)

    # 复核关键文件
    code, out = run(cli, f"grep -c '按发布时间（新→旧）' {REMOTE_DIR}/data/web/ledger_app.html; "
                         f"grep -n 'infodatepx' {REMOTE_DIR}/crawl/sources/jsggzy.py | head -2")
    print("=== UPLOAD VERIFY ===\n" + out[:300], flush=True)

    # ---- 3) 重建 ----
    print("=== BUILD (up -d --build, may take minutes) ===", flush=True)
    code, out = sudo_run(
        cli,
        f"sh -c 'cd {REMOTE_DIR} && /usr/local/bin/docker-compose up -d --build 2>&1 | tail -25'",
        pw,
        timeout=1200,
    )
    print(out[-2000:], flush=True)
    print("BUILD_EXIT", code, flush=True)

    # ---- 4) 自检 ----
    code, out = sudo_run(cli, "/usr/local/bin/docker ps --format '{{.Names}}|{{.Status}}' | head -6", pw)
    print("=== AFTER: DOCKER PS ===\n" + out[:500], flush=True)
    code, out = run(cli, "curl -s -m 10 http://127.0.0.1:8765/api/health || echo HEALTH_FAIL")
    print("=== HEALTH ===\n" + out[:300], flush=True)
    code, out = run(cli,
                    "curl -s -m 10 http://127.0.0.1:8765/ | grep -c '按发布时间（新→旧）'; "
                    "curl -s -m 10 'http://127.0.0.1:8765/api/notices?limit=30' | "
                    "grep -o '\"publish_date\":\"[^\"]*\"' | head -12")
    print("=== UI+API SORT CHECK ===\n" + out[:900], flush=True)
    code, out = sudo_run(cli, "/usr/local/bin/docker logs spiderman_ledger --tail 8 2>&1", pw)
    print("=== LOG TAIL ===\n" + out[:600], flush=True)
    cli.close()
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
