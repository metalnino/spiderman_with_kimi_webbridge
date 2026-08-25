"""瑞达恒「邮件验证码回传」登录闭环（人不在家也能完成登录，无需远程桌面）。

流程（auto）：
1. 桥开 bid.rccchina.com/login → 填手机号 → 点「获取验证码」（短信发到用户手机）；
2. 给用户发邮件（默认 279152260@qq.com）：「请直接回复本邮件，附短信验证码」；
3. 轮询 Gmail 收件箱（IMAP，主题含 #tag 的回复）提取 4~6 位验证码（验证码约 5 分钟有效，轮询窗口默认 8 分钟）；
4. 桥填手机号+验证码 → 提交登录 → CDP 导出全量 Cookie → data/sessions/rccchina.cookies.json →
   关闭 captcha 待办 → 回发「登录完成」确认邮件。

凭据与配置（全部在 .env，不进 git）：
  GMAIL_USER / GMAIL_APP_PASSWORD（Gmail 需开 IMAP；可复用发日报的应用专用密码）
  RCCCHINA_PHONE（瑞达恒登录手机号）
  EMAIL_TO（可选，默认 279152260@qq.com）
诚实原则：任何一步失败如实返回错误；验证码过期/收不到 → 本轮放弃，下轮自动重新请求；
同一封回复只尝试一次（尝试后标已读），绝不反复重放验证码。
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts import email_gateway as eg  # noqa: E402
from crawl import cookie_store  # noqa: E402
from crawl import webbridge_client as wb  # noqa: E402
from crawl.captcha_queue import close_todo, list_open  # noqa: E402

LOGIN_URL = "https://bid.rccchina.com/login"
SESSION = "rccchina-auth"
MARKER = ROOT / "data" / "web" / "rccchina_email_pending.json"

# 分析与风控类 cookie（不属于登录态）：登录成功判据 = 存在名单外的 cookie
NOISE_COOKIE_PREFIXES = (
    "Hm_lvt_", "Hm_lpvt_", "HMACCOUNT", "guest_id", "HWWAF", "WAFSESS", "preurl",
    "seo_", "qlm_", "captcha_rand_code", "first_login_open", "login_open", "cloudwaf",
)


def _phone() -> str:
    from db import load_env

    return (load_env().get("RCCCHINA_PHONE") or "").strip()


def _creds_ready() -> bool:
    u, p = eg.creds()
    return bool(u and p)


def _fill_phone_js(phone: str) -> str:
    return (
        "(() => {"
        " const inputs=[...document.querySelectorAll('input')];"
        " const target=inputs.find(i=>/手机|电话|手机号|phone|mobile/i.test((i.placeholder||'')+(i.name||'')+(i.type||'')));"
        " if(!target) return JSON.stringify({ok:false, reason:'no_phone_input', inputs: inputs.slice(0,5).map(i=>(i.placeholder||i.type||''))});"
        " target.focus(); target.value=" + json.dumps(phone) + ";"
        " target.dispatchEvent(new Event('input',{bubbles:true}));"
        " target.dispatchEvent(new Event('change',{bubbles:true}));"
        " const btns=[...document.querySelectorAll('button,a,span,i,div')];"
        " let clicked=false;"
        " for(const b of btns.slice(0,600)){const t=((b.textContent||'')+(b.getAttribute('aria-label')||'')).trim();"
        "  if(/获取验证码|发送验证码|获取短信|获取动态码/.test(t)){b.click();clicked=true;break;}}"
        " return JSON.stringify({ok:true, clicked});"
        "})()"
    )


def _fill_code_js(phone: str, code: str) -> str:
    return (
        "(() => {"
        " const inputs=[...document.querySelectorAll('input')];"
        " const phoneInput=inputs.find(i=>/手机|电话|手机号|phone|mobile/i.test((i.placeholder||'')+(i.name||'')+(i.type||'')));"
        " const codeInput=inputs.find(i=>/验证码|动态码|code|sms/i.test((i.placeholder||'')+(i.name||'')+(i.type||'')));"
        " if(phoneInput){phoneInput.focus();phoneInput.value=" + json.dumps(phone) + ";"
        "  phoneInput.dispatchEvent(new Event('input',{bubbles:true}));}"
        " if(!codeInput) return JSON.stringify({ok:false, reason:'no_code_input'});"
        " codeInput.focus(); codeInput.value=" + json.dumps(code) + ";"
        " codeInput.dispatchEvent(new Event('input',{bubbles:true}));"
        " codeInput.dispatchEvent(new Event('change',{bubbles:true}));"
        " let clicked=false;"
        " const btns=[...document.querySelectorAll('button,a,span,i,div')];"
        " for(const b of btns.slice(0,600)){const t=((b.textContent||'')+(b.getAttribute('aria-label')||'')).trim();"
        "  if(/^登\\s*录$|^注\\s*册$|登\\s*录|注\\s*册/.test(t)&&t.length<6){b.click();clicked=true;break;}}"
        " return JSON.stringify({ok:true, clicked});"
        "})()"
    )


def _read_page_text_js() -> str:
    return "(() => ((document.body.innerText||'').replace(/\\s+/g,' ').slice(0,800)))()"


def _bridge_eval(js: str) -> dict:
    r = wb.evaluate(js, session=SESSION)
    if not r.get("ok"):
        raise RuntimeError(f"bridge_evaluate_failed: {str(r.get('error'))[:120]}")
    v = (r.get("data") or {}).get("value")
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            pass
    return {"value": v}


def _bridge_status() -> dict:
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:10086/", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {"up": True, "extensions": int(data.get("extensions_connected") or 0)}
    except Exception:
        return {"up": False, "extensions": 0}


# ---------------------------------------------------------------- 三步骤 ---

def request_code(phone: str, to: str, tag: str) -> dict:
    """开登录页→填手机号→点获取验证码→发请求邮件→写 marker。"""
    st = wb.ensure_bridge(wait_sec=60)
    if not st.get("extensions"):
        return {"ok": False, "error": "webbridge_not_available"}
    wb.navigate(LOGIN_URL, session=SESSION, group_title="rccchina-auth", new_tab=True)
    time.sleep(6)
    act = _bridge_eval(_fill_phone_js(phone))
    time.sleep(5)
    page_text = _bridge_eval(_read_page_text_js()).get("value") or ""
    hint = ""
    for k in ("未注册", "已注册", "手机号错误", "格式", "频繁", "失败"):
        if k in str(page_text):
            hint = f"（页面提示：{k}）"
            break
    subject = f"【爬虫验证码】瑞达恒登录 {tag}"
    body = (
        f"爬虫需要登录瑞达恒（bid.rccchina.com），已用手机号 {phone} 请求短信验证码。\n\n"
        f"请直接【回复本邮件】，内容只写收到的验证码（4~6 位数字），5 分钟内有效。\n"
        f"{hint}\n\n（本邮件由爬虫自动发送；无需登录电脑，人在哪都能完成）"
    )
    sent = eg.send(to, subject, body)
    if not sent.get("ok"):
        return {"ok": False, "error": f"email_send_failed: {sent.get('error')}"}
    marker = {"tag": tag, "phone": phone, "to": to, "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    MARKER.parent.mkdir(parents=True, exist_ok=True)
    MARKER.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "tag": tag, "filled": act.get("value"), "page_hint": hint}


def complete_login(marker: dict) -> dict:
    """读回复→提取验证码→填码提交→导出 Cookie→保存→关待办→回确认邮件。"""
    tag = marker.get("tag") or ""
    replies = eg.poll_replies(tag)
    if not replies:
        return {"ok": False, "error": "no_reply_yet"}
    reply = replies[0]
    code = eg.extract_code(reply.get("subject") or "", reply.get("body") or "")
    eg.mark_seen([r.get("uid") or "" for r in replies])
    if not code:
        return {"ok": False, "error": "reply_without_code"}
    st = _bridge_status()
    if not st.get("extensions"):
        return {"ok": False, "error": "webbridge_not_available", "code_received": True}
    wb.navigate(LOGIN_URL, session=SESSION, new_tab=False)
    time.sleep(5)
    act = _bridge_eval(_fill_code_js(marker.get("phone") or "", code))
    time.sleep(8)
    page_text = _bridge_eval(_read_page_text_js()).get("value") or ""
    success_hint = any(k in str(page_text) for k in ("退出", "我的", "用户名", "会员", "工作台"))
    ck = wb.export_cookies([f"https://{h}" for h in ("bid.rccchina.com", "www.rccchina.com", "rccchina.com")], session=SESSION)
    header = (ck.get("cookie") or "").strip() if ck.get("ok") else ""
    session_cookies = [
        c.get("name") for c in (ck.get("cookies") or [])
        if not any((c.get("name") or "").startswith(p) for p in NOISE_COOKIE_PREFIXES)
    ]
    if not success_hint and not session_cookies:
        return {"ok": False, "error": f"login_not_confirmed: {str(page_text)[:200]}"}
    cookie_store.save_cookie_header("rccchina", header, meta={"method": "email_auth", "tag": tag})
    closed = 0
    for t in list_open():
        if t.get("source_id") == "rccchina":
            closed += 1 if close_todo(int(t["id"]), note="邮件验证码闭环登录完成，Cookie 已保存") else 0
    eg.send(
        marker.get("to") or eg.default_to(),
        f"【爬虫】瑞达恒登录完成 {tag}",
        f"瑞达恒已登录完成，Cookie 已保存至本地供后续抓取复用（登录态 cookie {len(session_cookies)} 个，页面提示登录成功={success_hint}）。"
        f"\n\n无需其他操作；若后续会话失效，会再次自动发验证码请求邮件。",
    )
    if MARKER.exists():
        MARKER.unlink()
    return {"ok": True, "cookie_len": len(header), "session_cookie_names": session_cookies[:10], "closed_todos": closed}


def auto(phone: str | None = None, to: str | None = None, *, timeout_min: int = 8, poll_sec: int = 30) -> dict:
    """request → 轮询 → complete 全闭环。返回 {ok, error|...}。"""
    if not _creds_ready():
        return {"ok": False, "error": "no_email_credentials", "skipped": True}
    phone = (phone or _phone()).strip()
    if not phone:
        return {"ok": False, "error": "no_phone: .env 缺 RCCCHINA_PHONE", "skipped": True}
    marker = None
    if MARKER.exists():
        try:
            marker = json.loads(MARKER.read_text(encoding="utf-8"))
        except Exception:
            marker = None
        # 超过 6 小时的旧 marker 作废：旧验证码早已过期，重新发请求邮件（每轮最多一封）
        if marker:
            try:
                age_h = (datetime.now() - datetime.strptime(marker.get("created_at") or "2000-01-01 00:00:00", "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600
                if age_h > 6:
                    marker = None
            except Exception:
                marker = None
    if not marker:
        tag = f"rcv{int(time.time())}"
        req = request_code(phone, to or eg.default_to(), tag)
        if not req.get("ok"):
            return req
        marker = {"tag": tag, "phone": phone, "to": to or eg.default_to()}
    deadline = time.time() + timeout_min * 60
    while time.time() < deadline:
        res = complete_login(marker)
        if res.get("ok"):
            return res
        if res.get("code_received") or res.get("error") not in ("no_reply_yet",):
            # 收到过回复但没成（过期/页面异常）：本轮放弃，不无限重试
            return {"ok": False, "error": res.get("error"), "gave_up": True}
        time.sleep(poll_sec)
    return {"ok": False, "error": "code_timeout", "gave_up": True}


def auto_if_needed(rccchina_error: str | None) -> dict:
    """采集员钩子：rccchina 本轮撞墙 → 跑邮件闭环。凭据/手机号没配齐则静默跳过（返回 skipped）。"""
    if rccchina_error and ("register_wall" in rccchina_error or "cookie_ok_api_unmapped" in rccchina_error):
        if not _creds_ready() or not _phone():
            return {"ok": False, "error": "email_auth_not_configured", "skipped": True}
        return auto(timeout_min=8)
    return {"ok": False, "error": "no_wall_error", "skipped": True}


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--request", action="store_true")
    ap.add_argument("--complete", action="store_true")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--phone", default=None)
    ap.add_argument("--to", default=None)
    ap.add_argument("--timeout-min", type=int, default=8)
    args = ap.parse_args()
    if args.request:
        tag = f"rcv{int(time.time())}"
        print(json.dumps(request_code(args.phone or _phone(), args.to or eg.default_to(), tag), ensure_ascii=False))
    elif args.complete:
        marker = json.loads(MARKER.read_text(encoding="utf-8")) if MARKER.exists() else {}
        print(json.dumps(complete_login(marker), ensure_ascii=False))
    else:
        print(json.dumps(auto(args.phone, args.to, timeout_min=args.timeout_min), ensure_ascii=False))


if __name__ == "__main__":
    main()
