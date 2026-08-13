"""Upload project into Synology /docker/spiderman using in-page authenticated XHR."""
from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WB = "http://127.0.0.1:10086/command"
SESSION = "nas-deploy"
DEST = "/docker/spiderman"

INCLUDE_DIRS = ["sql", "config", "crawl", "scripts/jobs"]
INCLUDE_FILES = [
    "Dockerfile",
    "docker-compose.yml",
    ".dockerignore",
    ".env.example",
    "requirements.txt",
    "scripts/docker_entrypoint.sh",
    "scripts/migrate_ops.py",
    "scripts/db.py",
    "scripts/run_tests.py",
    "data/web/ledger_app.html",
]


def wb(action: str, args: dict | None = None, timeout: int = 120) -> dict:
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
            return {"ok": False, "error": raw[:800]}


def eval_json(code: str, timeout: int = 120) -> dict:
    r = wb("evaluate", {"code": code}, timeout=timeout)
    val = (r.get("data") or {}).get("value")
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {"raw": val}
    return {"wb_ok": r.get("ok"), "value": val, "error": r.get("error")}


def collect_files() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for rel in INCLUDE_FILES:
        p = ROOT / rel
        if p.is_file():
            out[rel.replace("\\", "/")] = p.read_bytes()
    for d in INCLUDE_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for f in base.rglob("*"):
            if not f.is_file():
                continue
            if "__pycache__" in f.parts or f.suffix == ".pyc":
                continue
            out[f.relative_to(ROOT).as_posix()] = f.read_bytes()
    env = ROOT / ".env"
    if env.exists():
        out[".env"] = env.read_bytes()
    return out


TOKEN_JS = "(window.SYNO && SYNO.SDS && SYNO.SDS.Session && SYNO.SDS.Session.SynoToken) || ''"


def ensure_folder(path: str) -> dict:
    # Create nested folders under /docker
    code = f"""(() => {{
      const token = {TOKEN_JS};
      const full = {json.dumps(path)};
      const parts = full.split('/').filter(Boolean);
      let cur = '';
      const logs = [];
      for (const p of parts) {{
        cur = (cur || '') + '/' + p;
        if (cur === '/docker') continue;
        const parentPath = cur.substring(0, cur.lastIndexOf('/')) || '/';
        const name = p;
        const url = '/webapi/entry.cgi?api=SYNO.FileStation.CreateFolder&version=2&method=create'
          + '&folder_path=' + encodeURIComponent(parentPath)
          + '&name=' + encodeURIComponent(name)
          + '&force_parent=true'
          + '&SynoToken=' + encodeURIComponent(token);
        const xhr = new XMLHttpRequest();
        xhr.open('GET', url, false);
        xhr.withCredentials = true;
        xhr.setRequestHeader('X-SYNO-TOKEN', token);
        xhr.send(null);
        logs.push({{path: cur, status: xhr.status, body: xhr.responseText.slice(0,200)}});
      }}
      return JSON.stringify({{ok:true, logs}});
    }})()"""
    return eval_json(code)


def upload_one(folder: str, name: str, data: bytes) -> dict:
    # Build multipart in JS from base64
    b64 = base64.b64encode(data).decode("ascii")
    code = f"""(() => {{
      const token = {TOKEN_JS};
      const folder = {json.dumps(folder)};
      const name = {json.dumps(name)};
      const b64 = {json.dumps(b64)};
      const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
      const boundary = '----Spiderman' + Date.now();
      const enc = new TextEncoder();
      const parts = [];
      function push(s) {{ parts.push(enc.encode(s)); }}
      function field(k,v) {{
        push('--' + boundary + '\\r\\n');
        push('Content-Disposition: form-data; name=\"' + k + '\"\\r\\n\\r\\n');
        push(v + '\\r\\n');
      }}
      field('api','SYNO.FileStation.Upload');
      field('version','2');
      field('method','upload');
      field('path', folder);
      field('create_parents','true');
      field('overwrite','true');
      field('SynoToken', token);
      push('--' + boundary + '\\r\\n');
      push('Content-Disposition: form-data; name=\"file\"; filename=\"' + name + '\"\\r\\n');
      push('Content-Type: application/octet-stream\\r\\n\\r\\n');
      parts.push(bytes);
      push('\\r\\n--' + boundary + '--\\r\\n');
      let len = 0; for (const p of parts) len += p.length;
      const body = new Uint8Array(len);
      let off = 0;
      for (const p of parts) {{ body.set(p, off); off += p.length; }}
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/webapi/entry.cgi', false);
      xhr.withCredentials = true;
      xhr.setRequestHeader('X-SYNO-TOKEN', token);
      xhr.setRequestHeader('Content-Type', 'multipart/form-data; boundary=' + boundary);
      xhr.send(body);
      return JSON.stringify({{status: xhr.status, body: xhr.responseText.slice(0,500)}});
    }})()"""
    return eval_json(code, timeout=180)


def main() -> None:
    wb("navigate", {"url": "https://fc9966.synology.me:5001/", "newTab": False})
    time.sleep(2)
    shares = eval_json(
        """(() => {
          const token = (window.SYNO && SYNO.SDS && SYNO.SDS.Session && SYNO.SDS.Session.SynoToken) || '';
          const xhr = new XMLHttpRequest();
          xhr.open('GET', '/webapi/entry.cgi?api=SYNO.FileStation.List&version=2&method=list_share&SynoToken=' + encodeURIComponent(token), false);
          xhr.withCredentials = true;
          xhr.setRequestHeader('X-SYNO-TOKEN', token);
          xhr.send(null);
          return JSON.stringify({status: xhr.status, body: xhr.responseText.slice(0,800)});
        })()"""
    )
    print("SHARES", json.dumps(shares, ensure_ascii=False)[:500])

    print("MKDIR", ensure_folder(DEST))
    files = collect_files()
    print("FILE_COUNT", len(files), "BYTES", sum(len(v) for v in files.values()))
    ok = fail = 0
    for rel, raw in sorted(files.items()):
        parent = str(Path(rel).parent).replace("\\", "/")
        folder = DEST if parent in (".", "") else f"{DEST}/{parent}"
        if parent not in (".", ""):
            ensure_folder(folder)
        name = Path(rel).name
        res = upload_one(folder, name, raw)
        body = ""
        if isinstance(res, dict):
            body = res.get("body") or res.get("raw") or json.dumps(res, ensure_ascii=False)
        success = isinstance(body, str) and ("\"success\":true" in body.replace(" ", "") or '"success": true' in body)
        if success:
            ok += 1
            print("OK", rel)
        else:
            fail += 1
            print("FAIL", rel, json.dumps(res, ensure_ascii=False)[:220])
    print("SUMMARY", {"ok": ok, "fail": fail, "dest": DEST})


if __name__ == "__main__":
    main()
