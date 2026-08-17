"""NAS 部署验收 v2：docker 全路径。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parents[1]
DOCKER = "/var/packages/ContainerManager/target/usr/bin/docker"


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

    def sudo(cmd: str, timeout: int = 900) -> str:
        stdin, stdout, stderr = cli.exec_command(f"sudo -S -p '' {cmd}", get_pty=True, timeout=timeout)
        stdin.write(pw + "\n")
        stdin.flush()
        out = stdout.read().decode("utf-8", "ignore")
        err = stderr.read().decode("utf-8", "ignore")
        return (out + "\n" + err).strip()

    print("CODE:", sudo(
        f"{DOCKER} exec spiderman_ledger python -c \"from crawl.sources.base import SourceError; from crawl.sources.ccgp import CcgpSource; print('SourceError=ok'); print('region:', CcgpSource.extract_region('中标公告 | 上海 | 服务/商务')); print('city:', CcgpSource().city_for('', '上海'))\""
    )[-400:], flush=True)

    print("=== NAS incremental crawl ===", flush=True)
    out = sudo(
        f"{DOCKER} exec -e CCGP_BLOCK_COOLDOWN_SEC=15,30,60 -e SPIDER_RATE_LIMIT_COOLDOWN_SEC=30 "
        "spiderman_ledger python scripts/jobs/run_incremental.py --pages 1 2>&1 | tail -30",
        timeout=700,
    )
    print(out[-2500:], flush=True)

    print("=== runs tail ===", flush=True)
    out = sudo(
        f"{DOCKER} exec spiderman_ledger python -c \"import sys; sys.path.insert(0,'scripts'); from db import connect; c=connect(); cur=c.cursor(); cur.execute('SELECT id,source_id,status,item_count,note FROM crawl_runs ORDER BY id DESC LIMIT 3'); [print(dict(x)) for x in cur.fetchall()]; c.close()\""
    )
    print(out[-900:], flush=True)
    cli.close()


if __name__ == "__main__":
    main()
