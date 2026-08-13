"""Upload one file to /docker/spiderman via DSM WebBridge session."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WB = "http://127.0.0.1:10086/command"
SESSION = "nas-deploy2"
DEST = "/docker/spiderman"


def call(action: str, args: dict | None = None, timeout: int = 90) -> dict:
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
            return {"ok": False, "error": raw[:400]}


def main() -> None:
    rel = sys.argv[1] if len(sys.argv) > 1 else "Dockerfile"
    p = ROOT / rel
    text = p.read_text(encoding="utf-8").replace("\r\n", "\n")
    call("navigate", {"url": "https://fc9966.synology.me:5001/", "newTab": False})
    time.sleep(2)
    setc = "(() => { window.__up_text = " + json.dumps(text) + "; return JSON.stringify({n: window.__up_text.length}); })()"
    print("SET", call("evaluate", {"code": setc}))
    name = p.name
    code = f"""(() => {{
      const token = (window.SYNO && SYNO.SDS && SYNO.SDS.Session && SYNO.SDS.Session.SynoToken) || '';
      const text = window.__up_text || '';
      const bytes = new TextEncoder().encode(text);
      const boundary = '----Spiderman' + Date.now();
      const enc = new TextEncoder();
      const parts = [];
      const push = (s) => parts.push(enc.encode(s));
      const field = (k, v) => {{ push('--'+boundary+'\\r\\n'); push('Content-Disposition: form-data; name=\"'+k+'\"\\r\\n\\r\\n'); push(v+'\\r\\n'); }};
      field('api','SYNO.FileStation.Upload'); field('version','2'); field('method','upload');
      field('path', {json.dumps(DEST)}); field('create_parents','true'); field('overwrite','true'); field('SynoToken', token);
      push('--'+boundary+'\\r\\n');
      push('Content-Disposition: form-data; name=\"file\"; filename=\"'+{json.dumps(name)}+'\"\\r\\n');
      push('Content-Type: application/octet-stream\\r\\n\\r\\n');
      parts.push(bytes); push('\\r\\n--'+boundary+'--\\r\\n');
      let len=0; for (const x of parts) len+=x.length;
      const body=new Uint8Array(len); let off=0; for (const x of parts){{ body.set(x,off); off+=x.length; }}
      const xhr=new XMLHttpRequest(); xhr.open('POST','/webapi/entry.cgi',false); xhr.withCredentials=true;
      xhr.setRequestHeader('X-SYNO-TOKEN', token);
      xhr.setRequestHeader('Content-Type','multipart/form-data; boundary='+boundary);
      xhr.send(body);
      return JSON.stringify({{status:xhr.status, body:xhr.responseText.slice(0,300)}});
    }})()"""
    print("UP", call("evaluate", {"code": code}))


if __name__ == "__main__":
    main()
