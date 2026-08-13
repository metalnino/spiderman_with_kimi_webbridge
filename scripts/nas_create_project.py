"""Create/start Synology Container Manager project via SYNO.Docker.Project API."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

WB = "http://127.0.0.1:10086/command"
SESSION = "nas-deploy"


def wb(action: str, args: dict | None = None, timeout: int = 180) -> dict:
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


def eval_json(code: str, timeout: int = 180) -> dict:
    r = wb("evaluate", {"code": code}, timeout=timeout)
    val = (r.get("data") or {}).get("value")
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {"raw": val}
    return {"wb": r}


def api(method: str, extra: str = "", timeout: int = 180) -> dict:
    code = f"""(() => {{
      const token = (window.SYNO && SYNO.SDS && SYNO.SDS.Session && SYNO.SDS.Session.SynoToken) || '';
      let url = '/webapi/entry.cgi?api=SYNO.Docker.Project&version=1&method={method}'
        + '&SynoToken=' + encodeURIComponent(token)
        + {json.dumps(extra)};
      const xhr = new XMLHttpRequest();
      xhr.open('GET', url, false);
      xhr.withCredentials = true;
      xhr.setRequestHeader('X-SYNO-TOKEN', token);
      try {{
        xhr.send(null);
        return JSON.stringify({{status: xhr.status, body: xhr.responseText.slice(0, 3000)}});
      }} catch (e) {{
        return JSON.stringify({{ok:false, error:String(e)}});
      }}
    }})()"""
    return eval_json(code, timeout=timeout)


def main() -> None:
    print("LIST", api("list"))
    # create project pointing to uploaded compose dir
    # common params: name, path
    creates = [
        "&name=spiderman&path=%2Fdocker%2Fspiderman",
        "&name=spiderman&share_path=%2Fdocker%2Fspiderman",
        "&project_name=spiderman&path=%2Fdocker%2Fspiderman",
    ]
    for extra in creates:
        r = api("create", extra)
        print("CREATE_TRY", extra, json.dumps(r, ensure_ascii=False)[:500])
        body = r.get("body") or ""
        if '"success":true' in body.replace(" ", ""):
            break
    print("LIST2", api("list"))
    for m in ("build", "start", "update"):
        r = api(m, "&name=spiderman")
        print(m.upper(), json.dumps(r, ensure_ascii=False)[:500])


if __name__ == "__main__":
    main()
