"""Build/start spiderman project on Synology."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

WB = "http://127.0.0.1:10086/command"
SESSION = "nas-deploy"
PROJECT_ID = "7d0829fd-d030-4b53-a233-99c17ce4ce96"


def wb(action: str, args: dict | None = None, timeout: int = 300) -> dict:
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


def eval_json(code: str, timeout: int = 300) -> dict:
    r = wb("evaluate", {"code": code}, timeout=timeout)
    val = (r.get("data") or {}).get("value")
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {"raw": val}
    return {"wb": r}


def call_project(method: str, params: dict, timeout: int = 300) -> dict:
    # Prefer POST application/x-www-form-urlencoded
    qs = "&".join(f"{k}={urllib.request.quote(str(v))}" for k, v in params.items())
    code = f"""(() => {{
      const token = (window.SYNO && SYNO.SDS && SYNO.SDS.Session && SYNO.SDS.Session.SynoToken) || '';
      const params = new URLSearchParams();
      params.set('api', 'SYNO.Docker.Project');
      params.set('version', '1');
      params.set('method', {json.dumps(method)});
      params.set('SynoToken', token);
      const extra = {json.dumps(params)};
      for (const [k,v] of Object.entries(extra)) params.set(k, String(v));
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/webapi/entry.cgi', false);
      xhr.withCredentials = true;
      xhr.setRequestHeader('X-SYNO-TOKEN', token);
      xhr.setRequestHeader('Content-Type', 'application/x-www-form-urlencoded; charset=UTF-8');
      xhr.send(params.toString());
      return JSON.stringify({{status: xhr.status, body: xhr.responseText.slice(0, 4000)}});
    }})()"""
    return eval_json(code, timeout=timeout)


def main() -> None:
    for method, params in [
        ("get", {"id": PROJECT_ID}),
        ("build_stream", {"id": PROJECT_ID}),
        ("build", {"id": PROJECT_ID}),
        ("start", {"id": PROJECT_ID}),
        ("stop", {"id": PROJECT_ID}),
        ("compose_build", {"id": PROJECT_ID}),
        ("compose_up", {"id": PROJECT_ID}),
        ("build", {"id": PROJECT_ID, "name": "spiderman"}),
        ("start", {"id": PROJECT_ID, "name": "spiderman"}),
    ]:
        r = call_project(method, params)
        print(method, json.dumps(r, ensure_ascii=False)[:600])
        time.sleep(0.3)


if __name__ == "__main__":
    main()
