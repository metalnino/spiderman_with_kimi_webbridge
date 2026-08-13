"""Upload deploy bundle to Synology via File Station WebAPI using WebBridge DSM cookie."""
from __future__ import annotations

import io
import json
import tarfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WB = "http://127.0.0.1:10086/command"
DSM = "https://fc9966.synology.me:5001"
SESSION = "nas-deploy"

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


def wb(action: str, args: dict | None = None, timeout: int = 60) -> dict:
    body = json.dumps({"action": action, "args": args or {}, "session": SESSION}, ensure_ascii=False).encode()
    req = urllib.request.Request(WB, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return json.loads(raw)
        except Exception:
            return {"ok": False, "error": raw[:500]}


def dsm_cookie() -> str:
    r = wb(
        "evaluate",
        {
            "code": "(() => ({cookie: document.cookie || '', href: location.href, title: document.title}))()"
        },
    )
    val = (r.get("data") or {}).get("value")
    if isinstance(val, str):
        try:
            val = json.loads(val)
        except Exception:
            pass
    if isinstance(val, dict):
        return val.get("cookie") or ""
    return ""


def api_get(path: str, params: dict, cookie: str) -> dict:
    q = urllib.parse.urlencode(params)
    url = f"{DSM}{path}?{q}"
    req = urllib.request.Request(url, headers={"Cookie": cookie, "User-Agent": "spiderman-deploy"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def make_tar() -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel in INCLUDE:
            p = ROOT / rel
            if not p.exists():
                continue
            if p.is_file():
                tar.add(p, arcname=f"spiderman/{rel}")
            else:
                for f in p.rglob("*"):
                    if f.is_file() and "__pycache__" not in str(f) and ".pyc" not in f.name:
                        tar.add(f, arcname=f"spiderman/{f.relative_to(ROOT).as_posix()}")
        # include .env if present (needed to run); never commit
        env = ROOT / ".env"
        if env.exists():
            tar.add(env, arcname="spiderman/.env")
    return buf.getvalue()


def upload_file(cookie: str, dest_dir: str, filename: str, data: bytes) -> dict:
    # Synology FileStation upload: SYNO.FileStation.Upload
    boundary = "----SpidermanBoundary7MA4YWxkTrZu0gW"
    fields = {
        "api": "SYNO.FileStation.Upload",
        "version": "2",
        "method": "upload",
        "path": dest_dir,
        "create_parents": "true",
        "overwrite": "true",
    }
    body = io.BytesIO()
    for k, v in fields.items():
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    body.write(f"--{boundary}\r\n".encode())
    body.write(
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/gzip\r\n\r\n".encode()
    )
    body.write(data)
    body.write(f"\r\n--{boundary}--\r\n".encode())
    raw = body.getvalue()
    req = urllib.request.Request(
        f"{DSM}/webapi/entry.cgi",
        data=raw,
        headers={
            "Cookie": cookie,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "spiderman-deploy",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def main() -> None:
    cookie = dsm_cookie()
    print("COOKIE_LEN", len(cookie))
    if not cookie:
        raise SystemExit("no DSM cookie from WebBridge; open DSM tab in WebBridge first")

    # probe auth
    try:
        info = api_get(
            "/webapi/entry.cgi",
            {"api": "SYNO.API.Info", "version": "1", "method": "query", "query": "SYNO.FileStation.List"},
            cookie,
        )
        print("API_INFO", json.dumps(info, ensure_ascii=False)[:300])
    except Exception as e:
        print("API_INFO_ERR", e)

    tar = make_tar()
    print("TAR_BYTES", len(tar))
    # upload to docker shared folder commonly /docker or /volume1/docker
    for dest in ("/docker", "/volume1/docker", "/homes"):
        try:
            out = upload_file(cookie, dest, "spiderman_deploy.tar.gz", tar)
            print("UPLOAD", dest, json.dumps(out, ensure_ascii=False)[:500])
            if out.get("success"):
                print("OK_DEST", dest)
                break
        except Exception as e:
            print("UPLOAD_ERR", dest, e)


if __name__ == "__main__":
    main()
