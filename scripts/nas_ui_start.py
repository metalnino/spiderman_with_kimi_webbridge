"""Click Container Manager UI to build/start spiderman project."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

WB = "http://127.0.0.1:10086/command"
SESSION = "nas-deploy"


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


def eval_json(code: str) -> dict:
    r = wb("evaluate", {"code": code})
    val = (r.get("data") or {}).get("value")
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {"raw": val}
    return {"wb": r}


def click_contains(needle: str) -> dict:
    code = f"""(() => {{
      const needle = {json.dumps(needle)};
      const nodes = [...document.querySelectorAll('a,button,div,span,li,td,label')];
      const el = nodes.find(n => ((n.innerText||'') + ' ' + (n.getAttribute('title')||'')).replace(/\\s+/g,' ').includes(needle));
      if (!el) return JSON.stringify({{ok:false, needle}});
      el.click();
      return JSON.stringify({{ok:true, needle, text:(el.innerText||'').slice(0,60)}});
    }})()"""
    return eval_json(code)


def page_text() -> str:
    r = eval_json(
        """(() => JSON.stringify({text:(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,1800)}))()"""
    )
    return (r.get("text") if isinstance(r, dict) else "") or json.dumps(r, ensure_ascii=False)[:1800]


def async_build_start() -> dict:
    # non-blocking fetch so WebBridge won't hang
    code = """(() => {
      const token = (window.SYNO && SYNO.SDS && SYNO.SDS.Session && SYNO.SDS.Session.SynoToken) || '';
      const id = '7d0829fd-d030-4b53-a233-99c17ce4ce96';
      window.__spiderman_build = {started: Date.now(), logs: []};
      function post(method) {
        const params = new URLSearchParams();
        params.set('api', 'SYNO.Docker.Project');
        params.set('version', '1');
        params.set('method', method);
        params.set('id', id);
        params.set('SynoToken', token);
        return fetch('/webapi/entry.cgi', {
          method: 'POST',
          credentials: 'include',
          headers: {
            'X-SYNO-TOKEN': token,
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
          },
          body: params.toString()
        }).then(r => r.text()).then(t => {
          window.__spiderman_build.logs.push({method, t: t.slice(0, 1000)});
          return t;
        }).catch(e => {
          window.__spiderman_build.logs.push({method, err: String(e)});
        });
      }
      // try stream build then start
      post('build').then(() => post('start')).then(() => post('compose_up'));
      return JSON.stringify({ok:true, kicked:true});
    })()"""
    return eval_json(code)


def build_status() -> dict:
    return eval_json(
        """(() => JSON.stringify(window.__spiderman_build || {missing:true}))()"""
    )


def list_projects() -> dict:
    code = """(() => {
      const token = (window.SYNO && SYNO.SDS && SYNO.SDS.Session && SYNO.SDS.Session.SynoToken) || '';
      const params = new URLSearchParams();
      params.set('api','SYNO.Docker.Project');
      params.set('version','1');
      params.set('method','list');
      params.set('SynoToken', token);
      const xhr = new XMLHttpRequest();
      xhr.open('POST','/webapi/entry.cgi', false);
      xhr.withCredentials = true;
      xhr.setRequestHeader('X-SYNO-TOKEN', token);
      xhr.setRequestHeader('Content-Type','application/x-www-form-urlencoded; charset=UTF-8');
      xhr.send(params.toString());
      return JSON.stringify({status:xhr.status, body:xhr.responseText.slice(0,2500)});
    })()"""
    return eval_json(code)


def main() -> None:
    print("CLICK_CM", click_contains("Container Manager"))
    time.sleep(1)
    print("CLICK_PROJ", click_contains("项目"))
    time.sleep(1)
    print("PAGE1", page_text()[:800])
    print("KICK", async_build_start())
    for i in range(24):
        time.sleep(5)
        st = build_status()
        print("POLL", i, json.dumps(st, ensure_ascii=False)[:500])
        logs = (st.get("logs") if isinstance(st, dict) else None) or []
        if len(logs) >= 1:
            # keep polling until start returns
            if any("RUNNING" in json.dumps(x) or '"success":true' in json.dumps(x).replace(" ", "") for x in logs):
                if len(logs) >= 2:
                    break
    print("LIST", json.dumps(list_projects(), ensure_ascii=False)[:1500])


if __name__ == "__main__":
    main()
