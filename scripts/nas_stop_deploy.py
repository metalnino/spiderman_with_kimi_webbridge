"""NAS 部署停用：查状态 → 停容器（compose down，保留镜像/数据卷）→ 禁用 crontab 爬虫条目（先备份）。"""
from __future__ import annotations

import re
from datetime import datetime
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


def run(cli: paramiko.SSHClient, cmd: str, timeout: int = 120) -> tuple[int, str]:
    stdin, stdout, stderr = cli.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "ignore")
    err = stderr.read().decode("utf-8", "ignore")
    code = stdout.channel.recv_exit_status()
    return code, (out + "\n" + err).strip()


def sudo_run(cli, cmd: str, pw: str, timeout: int = 240) -> tuple[int, str]:
    stdin, stdout, stderr = cli.exec_command(
        f"sudo -S -p '' {cmd}", get_pty=True, timeout=timeout
    )
    stdin.write(pw + "\n")
    stdin.flush()
    out = stdout.read().decode("utf-8", "ignore")
    code = stdout.channel.recv_exit_status()
    return code, out.strip()


def main() -> None:
    host = env("NAS_SSH_HOST")
    port = int(env("NAS_SSH_PORT"))
    user = env("NAS_SSH_USER")
    pw = env("NAS_SSH_PASS")
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    cli.connect(host, port=port, username=user, password=pw, timeout=25)
    print("CONNECTED", host, flush=True)

    # 1) 现状
    code, out = run(cli, "docker ps -a --format '{{.Names}}|{{.Status}}' | head -15")
    print("=== DOCKER PS -a ===", code, out[:800], sep="\n", flush=True)
    code, out = run(cli, f"cd {REMOTE_DIR} && /usr/local/bin/docker-compose ps 2>&1 | head -10")
    print("=== COMPOSE PS ===", out[:600], sep="\n", flush=True)
    code, out = run(cli, "crontab -l 2>/dev/null | head -40")
    print("=== CRONTAB ===", out[:1200], sep="\n", flush=True)

    # 2) 停容器（compose down：停+删容器，镜像与数据卷保留，可随时 up 恢复）
    code, out = sudo_run(
        cli,
        f"sh -c 'cd {REMOTE_DIR} && /usr/local/bin/docker-compose down 2>&1 | tail -15'",
        pw,
    )
    print("=== COMPOSE DOWN ===", code, out[:800], sep="\n", flush=True)

    # 3) 禁用 crontab 中爬虫相关条目（备份后注释掉）
    code, out = run(cli, "crontab -l 2>/dev/null")
    if out.strip():
        lines = out.splitlines()
        backup = f"/tmp/crontab.bak.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        run(cli, f"crontab -l > {backup}")
        new_lines = []
        changed = 0
        for ln in lines:
            if re.search(r"spiderman|crawl|collector_run|run_multi_trial|8765|docker", ln, re.I):
                new_lines.append("# DISABLED-BY-SPIDERMAN-STOP " + ln)
                changed += 1
            else:
                new_lines.append(ln)
        if changed:
            script = "crontab - <<'EOF'\n" + "\n".join(new_lines) + "\nEOF"
            stdin, stdout, stderr = cli.exec_command(script, timeout=60)
            code2 = stdout.channel.recv_exit_status()
            print(f"=== CRONTAB DISABLED {changed} lines (backup {backup}) code={code2} ===", flush=True)
        else:
            print("=== CRONTAB: 无爬虫相关条目 ===", flush=True)
    else:
        print("=== CRONTAB: 空 ===", flush=True)

    # 4) 复核
    code, out = sudo_run(cli, "/usr/local/bin/docker ps --format '{{.Names}}|{{.Status}}' | head -10", pw)
    print("=== AFTER: DOCKER PS ===", out[:600] or "(无运行容器)", sep="\n", flush=True)
    cli.close()
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
