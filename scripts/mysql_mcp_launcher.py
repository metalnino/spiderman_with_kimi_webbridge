"""Launch MySQL MCP with credentials loaded from project .env (no secrets in mcp.json)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env():
    env = dict(os.environ)
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main():
    env = load_env()
    # common env names used by popular mysql MCP packages
    mapping = {
        "MYSQL_HOST": env.get("MYSQL_HOST"),
        "MYSQL_PORT": env.get("MYSQL_PORT", "3306"),
        "MYSQL_USER": env.get("MYSQL_USER"),
        "MYSQL_PASS": env.get("MYSQL_PASSWORD"),
        "MYSQL_PASSWORD": env.get("MYSQL_PASSWORD"),
        "MYSQL_DB": env.get("MYSQL_DATABASE"),
        "MYSQL_DATABASE": env.get("MYSQL_DATABASE"),
        "MYSQL_CHARSET": env.get("MYSQL_CHARSET", "utf8mb4"),
        "ALLOW_INSERT_OPERATION": env.get("MYSQL_ALLOW_INSERT", "true"),
        "ALLOW_UPDATE_OPERATION": env.get("MYSQL_ALLOW_UPDATE", "true"),
        "ALLOW_DELETE_OPERATION": env.get("MYSQL_ALLOW_DELETE", "false"),
    }
    for k, v in mapping.items():
        if v is not None:
            env[k] = str(v)

    npx = shutil.which("npx")
    if not npx:
        print("npx not found; install Node.js", file=sys.stderr)
        sys.exit(1)

    # @benborla442/mcp-server-mysql is widely used with Cursor
    cmd = [npx, "-y", "@benborla442/mcp-server-mysql"]
    # Windows 上保持 stdio 给 MCP；不要捕获输出
    raise SystemExit(subprocess.call(cmd, env=env))


if __name__ == "__main__":
    main()
