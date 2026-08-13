"""Fresh WebBridge session: kick project build/start asynchronously."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

WB = "http://127.0.0.1:10086/command"
SESSION = "nas-deploy2"
PROJECT_ID = "7d0829fd-d030-4b53-a233-99c17ce4ce96"


def call(action: str, args: dict | None = None, timeout: int = 45) -> dict:
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
    except Exception as e:
        return {"ok": False, "error": str(e)}


def ev(code: str, timeout: int = 45) -> dict:
    r = call("evaluate", {"code": code}, timeout=timeout)
    val = (r.get("data") or {}).get("value")
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {"raw": val, "wb": r}
    return r


def main() -> None:
    print("NAV", call("navigate", {"url": "https://fc9966.synology.me:5001/", "newTab": True, "group_title": "NAS2"}, timeout=60))
    time.sleep(6)
    print("PING", ev("(() => JSON.stringify({href:location.href, title:document.title, hasSYNO: typeof SYNO!=='undefined'}))()"))
    kick = ev(
        f"""(() => {{
          const token = (window.SYNO && SYNO.SDS && SYNO.SDS.Session && SYNO.SDS.Session.SynoToken) || '';
          const id = {json.dumps(PROJECT_ID)};
          window.__sp = {{logs: [], token: !!token}};
          const run = (method) => {{
            const p = new URLSearchParams();
            p.set('api','SYNO.Docker.Project');
            p.set('version','1');
            p.set('method', method);
            p.set('id', id);
            p.set('SynoToken', token);
            return fetch('/webapi/entry.cgi', {{
              method:'POST', credentials:'include',
              headers: {{'X-SYNO-TOKEN': token, 'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'}},
              body: p.toString()
            }}).then(r => r.text()).then(t => window.__sp.logs.push({{method, t: t.slice(0,1200)}}))
              .catch(e => window.__sp.logs.push({{method, err:String(e)}}));
          }};
          // build then start
          run('build').then(() => run('start'));
          return JSON.stringify({{ok:true, kicked:true, hasToken: !!token}});
        }})()"""
    )
    print("KICK", kick)
    for i in range(36):
        time.sleep(5)
        st = ev("(() => JSON.stringify(window.__sp || {{}}))()")
        print("POLL", i, json.dumps(st, ensure_ascii=False)[:700])
        logs = st.get("logs") if isinstance(st, dict) else None
        if logs and len(logs) >= 2:
            break
    # list status
    lst = ev(
        """(() => {
          const token = (window.SYNO && SYNO.SDS && SYNO.SDS.Session && SYNO.SDS.Session.SynoToken) || '';
          const p = new URLSearchParams();
          p.set('api','SYNO.Docker.Project'); p.set('version','1'); p.set('method','list'); p.set('SynoToken', token);
          return fetch('/webapi/entry.cgi', {method:'POST', credentials:'include',
            headers:{'X-SYNO-TOKEN':token,'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8'},
            body:p.toString()}).then(r=>r.text()).then(t => { window.__sp_list=t; return 'queued'; });
        })()"""
    )
    print("LIST_Q", lst)
    time.sleep(3)
    print("LIST", ev("(() => JSON.stringify({list:(window.__sp_list||'').slice(0,2000)}))()"))


if __name__ == "__main__":
    main()
