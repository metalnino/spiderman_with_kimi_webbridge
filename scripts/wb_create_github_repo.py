"""Use WebBridge to create GitHub repo in open Chrome."""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:10086/command"
SESSION = "gh-create"
REPO_NAME = "spiderman_with_kimi_webbridge"
DESC = "绿植招采线索：WebBridge+Python 多站爬取与汇聚"
OUT = Path(__file__).resolve().parents[1] / "data" / "multi_site" / "_wb_raw"


def call(action, args=None, timeout=180):
    body = {"action": action, "args": args or {}, "session": SESSION}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def eval_js(code: str):
    r = call("evaluate", {"code": code})
    if not r.get("ok"):
        return {"_error": r}
    v = (r.get("data") or {}).get("value")
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:
            return {"raw": v}
    return v


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {"steps": []}

    nav = call(
        "navigate",
        {
            "url": "https://github.com/new",
            "newTab": True,
            "group_title": "创建GitHub仓库",
        },
    )
    report["steps"].append({"nav": nav.get("ok")})
    time.sleep(6)

    page = eval_js(
        """(() => {
      const text=(document.body.innerText||'').replace(/\\s+/g,' ');
      return JSON.stringify({
        href: location.href,
        title: document.title,
        needLogin: /Sign in|登录/.test(document.title+text.slice(0,200)) || location.href.includes('/login'),
        hasRepoName: !!document.querySelector('#repository-name-input, input[name=\"repository[name]\"], input[aria-label*=\"Repository\"]')
      });
    })()"""
    )
    report["steps"].append({"page": page})
    (OUT / "gh_create_01_page.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if page.get("needLogin"):
        print("NEED_LOGIN", page.get("href"))
        (OUT / "gh_create_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    # fill repo name
    fill = eval_js(
        f"""(() => {{
      const name = {json.dumps(REPO_NAME)};
      const desc = {json.dumps(DESC)};
      const nameInput = document.querySelector('#repository-name-input')
        || document.querySelector('input[name=\"repository[name]\"]')
        || document.querySelector('input[aria-label*=\"Repository name\" i]')
        || [...document.querySelectorAll('input')].find(i => /repository|repo/i.test((i.id||'')+(i.name||'')+(i.getAttribute('aria-label')||'')));
      if (!nameInput) return JSON.stringify({{ok:false, reason:'no_name_input'}});
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
      setter.call(nameInput, name);
      nameInput.dispatchEvent(new Event('input', {{bubbles:true}}));
      nameInput.dispatchEvent(new Event('change', {{bubbles:true}}));

      const descInput = document.querySelector('#repository-description-input')
        || document.querySelector('input[name=\"repository[description]\"]')
        || document.querySelector('textarea[name=\"repository[description]\"]');
      if (descInput) {{
        const s2 = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')?.set
          || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value')?.set;
        if (s2) {{ s2.call(descInput, desc); descInput.dispatchEvent(new Event('input', {{bubbles:true}})); }}
      }}

      // prefer private if radio exists, else leave default
      const privateRadio = document.querySelector('#repository_visibility_private, input[value=\"private\"]');
      if (privateRadio) privateRadio.click();

      return JSON.stringify({{
        ok:true,
        nameValue: nameInput.value,
        href: location.href,
        privateClicked: !!privateRadio
      }});
    }})()"""
    )
    report["steps"].append({"fill": fill})
    time.sleep(2)

    # click create button
    click = eval_js(
        """(() => {
      const btns = [...document.querySelectorAll('button, [type=submit]')];
      let target = btns.find(b => /Create repository|Create repository|创建仓库/.test((b.innerText||'').trim()));
      if (!target) target = btns.find(b => /Create/.test((b.innerText||'').trim()) && !/template/i.test(b.innerText||''));
      if (!target) {
        return JSON.stringify({ok:false, reason:'no_create_btn', btnTexts: btns.slice(0,20).map(b=>(b.innerText||'').trim().slice(0,40))});
      }
      target.click();
      return JSON.stringify({ok:true, text:(target.innerText||'').trim().slice(0,60)});
    })()"""
    )
    report["steps"].append({"click": click})
    time.sleep(8)

    after = eval_js(
        """(() => {
      return JSON.stringify({
        href: location.href,
        title: document.title,
        created: /github\\.com\\/[^\\/]+\\/[^\\/]+/.test(location.href) && !/\\/new/.test(location.href)
      });
    })()"""
    )
    report["steps"].append({"after": after})
    report["repo_name"] = REPO_NAME
    report["result_url"] = after.get("href")
    (OUT / "gh_create_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"created": after.get("created"), "href": after.get("href"), "fill": fill, "click": click}, ensure_ascii=False))


if __name__ == "__main__":
    main()
