"""Poll Synology project status; start when build done."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

WB = "http://127.0.0.1:10086/command"
SESSION = "nas-deploy2"
PROJECT_ID = "7d0829fd-d030-4b53-a233-99c17ce4ce96"


def call(action: str, args: dict | None = None, timeout: int = 60) -> dict:
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


def list_projects() -> dict:
    code = """(() => {
      const token = (window.SYNO && SYNO.SDS && SYNO.SDS.Session && SYNO.SDS.Session.SynoToken) || '';
      const p = new URLSearchParams();
      p.set('api','SYNO.Docker.Project');
      p.set('version','1');
      p.set('method','list');
      p.set('SynoToken', token);
      const xhr = new XMLHttpRequest();
      xhr.open('POST','/webapi/entry.cgi', false);
      xhr.withCredentials = true;
      xhr.setRequestHeader('X-SYNO-TOKEN', token);
      xhr.setRequestHeader('Content-Type','application/x-www-form-urlencoded; charset=UTF-8');
      xhr.send(p.toString());
      return xhr.responseText;
    })()"""
    r = call("evaluate", {"code": code})
    val = (r.get("data") or {}).get("value")
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {"raw": val}
    return r


def start_project() -> dict:
    code = f"""(() => {{
      const token = (window.SYNO && SYNO.SDS && SYNO.SDS.Session && SYNO.SDS.Session.SynoToken) || '';
      const p = new URLSearchParams();
      p.set('api','SYNO.Docker.Project');
      p.set('version','1');
      p.set('method','start');
      p.set('id', {json.dumps(PROJECT_ID)});
      p.set('SynoToken', token);
      window.__start = 'pending';
      fetch('/webapi/entry.cgi', {{
        method:'POST', credentials:'include',
        headers:{{'X-SYNO-TOKEN':token,'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'}},
        body:p.toString()
      }}).then(r=>r.text()).then(t => {{ window.__start = t; }}).catch(e => {{ window.__start = String(e); }});
      return JSON.stringify({{ok:true}});
    }})()"""
    return call("evaluate", {"code": code})


def main() -> None:
    for i in range(60):
        data = list_projects()
        proj = (data.get("data") or {}).get(PROJECT_ID) or {}
        status = proj.get("status") or proj.get("state") or "?"
        print(f"[{i}] status={status} containers={proj.get('containerIds')}")
        if status in {"RUNNING", "ERROR", "STOPPED", "CREATED"} and status != "BUILDING":
            if status != "RUNNING":
                print("START", start_project())
                time.sleep(8)
                data = list_projects()
                proj = (data.get("data") or {}).get(PROJECT_ID) or {}
                print("AFTER_START", proj.get("status"), proj.get("containerIds"))
            break
        if status == "RUNNING":
            break
        time.sleep(10)
    print("FINAL", json.dumps((list_projects().get("data") or {}).get(PROJECT_ID), ensure_ascii=False)[:800])


if __name__ == "__main__":
    main()
