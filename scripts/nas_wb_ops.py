"""Operate Synology DSM via local WebBridge for deploy helpers."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:10086/command"
SESSION = "nas-deploy2"


def call(action: str, args: dict | None = None, timeout: int = 90) -> dict:
    body = json.dumps({"action": action, "args": args or {}, "session": SESSION}, ensure_ascii=False).encode()
    req = urllib.request.Request(BASE, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "ignore")
        try:
            return json.loads(raw)
        except Exception:
            return {"ok": False, "error": raw[:800]}


def dump(obj, n=5000):
    print(json.dumps(obj, ensure_ascii=False, indent=2)[:n])


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "nav":
        url = sys.argv[2] if len(sys.argv) > 2 else "https://fc9966.synology.me:5001/"
        dump(call("navigate", {"url": url, "newTab": True, "group_title": "NAS部署"}))
        return
    if cmd == "status":
        code = """(() => {
          const text = (document.body && document.body.innerText || '').replace(/\\s+/g,' ').slice(0,2000);
          const labels = [];
          document.querySelectorAll('[title], [aria-label], button, a, .x-tab-inner, .syno-ux-button').forEach(el => {
            const t = (el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || el.textContent || '').trim().replace(/\\s+/g,' ');
            if (t && t.length > 0 && t.length < 50) labels.push(t);
          });
          return JSON.stringify({href: location.href, title: document.title, text, labels: [...new Set(labels)].slice(0,100)});
        })()"""
        r = call("evaluate", {"code": code})
        # pretty print decoded value if string
        if r.get("ok") and isinstance((r.get("data") or {}).get("value"), str):
            try:
                r = {"ok": True, "page": json.loads(r["data"]["value"])}
            except Exception:
                pass
        dump(r)
        return
    if cmd == "click_contains":
        needle = sys.argv[2]
        code = f"""(() => {{
          const needle = {json.dumps(needle)};
          const nodes = [...document.querySelectorAll('a,button,div,span,li,label')];
          const el = nodes.find(n => {{
            const t = ((n.innerText||n.textContent||'') + ' ' + (n.getAttribute('title')||'') + ' ' + (n.getAttribute('aria-label')||'')).replace(/\\s+/g,' ').trim();
            return t.includes(needle);
          }});
          if (!el) return JSON.stringify({{ok:false, error:'not_found', needle}});
          el.click();
          return JSON.stringify({{ok:true, needle, tag: el.tagName, text:(el.innerText||'').slice(0,80)}});
        }})()"""
        dump(call("evaluate", {"code": code}))
        return
    if cmd == "click_text":
        needle = sys.argv[2]
        code = f"""(() => {{
          const needle = {json.dumps(needle)};
          const nodes = [...document.querySelectorAll('a,button,div,span,li')];
          const el = nodes.find(n => ((n.innerText||n.textContent||n.getAttribute('title')||'').trim() === needle)
            || ((n.getAttribute('aria-label')||'') === needle)
            || ((n.getAttribute('title')||'') === needle));
          if (!el) return JSON.stringify({{ok:false, error:'not_found', needle}});
          el.click();
          return JSON.stringify({{ok:true, needle, tag: el.tagName}});
        }})()"""
        dump(call("evaluate", {"code": code}))
        return
    if cmd == "eval":
        dump(call("evaluate", {"code": sys.argv[2]}))
        return
    print("usage: nav|status|click_text|click_contains|eval")


if __name__ == "__main__":
    main()
