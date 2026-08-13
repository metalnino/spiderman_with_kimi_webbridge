"""江苏招标网 jiangsu.zhaobiao.cn — 账号登录可选，列表主路径 HTTP。"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from db import load_env  # noqa: E402

from crawl import cookie_store
from crawl.captcha_queue import open_todo
from crawl.config_loader import sources_cfg
from crawl.models import Notice
from crawl.sources.base import BaseSource

HOME = "https://jiangsu.zhaobiao.cn"
LOGIN_PAGE = "https://user.zhaobiao.cn/login.html"
LOGIN_POST = "https://user.zhaobiao.cn/ssologin.do?method=loginPost"
def _decode_response(raw: bytes) -> str:
    for enc in ("utf-8", "gbk", "gb2312"):
        try:
            text = raw.decode(enc)
            if "绿化" in text or "招标" in text or enc == "gbk":
                return text
        except Exception:
            continue
    return raw.decode("utf-8", "ignore")


def _creds() -> tuple[str | None, str | None]:
    env = load_env()
    user = env.get("JIANGSU_ZHAOBIAO_USER") or env.get("ZHAOBIAO_JS_USER")
    pwd = env.get("JIANGSU_ZHAOBIAO_PASS") or env.get("ZHAOBIAO_JS_PASS")
    return (user.strip() if user else None), (pwd.strip() if pwd else None)


class JiangsuZhaobiaoSource(BaseSource):
    source_id = "jiangsu_zhaobiao"
    source_name = "江苏招标网"

    def __init__(self):
        super().__init__()
        self._login_state: dict = {"ok": False, "reason": "not_tried"}

    def ensure_login(self) -> dict:
        """Best-effort login. Slider captcha may require human; cookies reused from store."""
        if self._login_state.get("ok"):
            return self._login_state
        # reuse stored cookie
        if cookie_store.cookie_header(self.source_id):
            self.http.load_stored_cookies(self.source_id)
            self._login_state = {"ok": True, "reason": "cookie_store"}
            return self._login_state

        user, pwd = _creds()
        if not user or not pwd:
            self._login_state = {"ok": False, "reason": "missing_creds"}
            return self._login_state

        try:
            _, raw, final = self.http.request(LOGIN_PAGE, headers={"Referer": HOME})
            html = _decode_response(raw)
            payload = {}
            for m in re.finditer(r"<input[^>]+>", html, re.I):
                tag = m.group(0)
                nm = re.search(r'name=["\']([^"\']+)["\']', tag, re.I)
                val = re.search(r'value=["\']([^"\']*)["\']', tag, re.I)
                typ = (re.search(r'type=["\']([^"\']+)["\']', tag, re.I) or [None, "text"])[1].lower()
                if not nm or typ in {"submit", "button", "image"}:
                    continue
                payload[nm.group(1)] = val.group(1) if val else ""
            payload["loginType"] = payload.get("loginType") or "0"
            payload["loginUserId"] = user
            payload["loginPassword"] = pwd
            # 无验证码/滑块时可能直接失败；失败则登记人工待办
            body = urlencode(payload).encode("utf-8")
            code, raw2, final2 = self.http.request(
                LOGIN_POST,
                data=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": LOGIN_PAGE,
                    "Origin": "https://user.zhaobiao.cn",
                },
            )
            text2 = _decode_response(raw2)
            cookie_hdr = self.http._cookie_header or ""
            # jar cookies to header
            jar_bits = []
            for c in self.http.cj:
                jar_bits.append(f"{c.name}={c.value}")
            if jar_bits:
                cookie_hdr = "; ".join(jar_bits)
                self.http._cookie_header = cookie_hdr
            looks_fail = bool(
                re.search(r"验证码|滑块|密码错误|用户不存在|loginUserId|loginPassword", text2[:4000])
            ) and "login.html" in (final2 or "")
            if code == 200 and cookie_hdr and not looks_fail and "JSESSIONID" in cookie_hdr:
                # weak success signal
                if "loginPassword" not in text2[:2000] or "退出" in text2 or "会员中心" in text2:
                    cookie_store.save_cookie_header(
                        self.source_id, cookie_hdr, meta={"from": "login_post", "user": user}
                    )
                    self._login_state = {"ok": True, "reason": "login_post"}
                    return self._login_state
            # need human slider
            open_todo(
                self.source_id,
                LOGIN_PAGE,
                title="江苏招标网登录滑块/验证码",
                note="请登录后执行 solve_captcha done 保存 Cookie",
            )
            self._login_state = {"ok": False, "reason": "need_human_captcha", "final": final2}
            return self._login_state
        except Exception as e:  # noqa: BLE001
            self._login_state = {"ok": False, "reason": f"login_error:{e}"[:180]}
            return self._login_state

    def _parse_list(self, html: str, keyword: str) -> list[Notice]:
        notices: list[Notice] = []
        seen = set()
        pat = re.compile(
            r'<a[^>]+href="(https?://jiangsu\.zhaobiao\.cn/(bidding|succeed|change|other|project)_v_([a-f0-9]{16,})\.html)"[^>]*>(.*?)</a>',
            re.I | re.S,
        )
        for m in pat.finditer(html):
            url, kind, ext, inner = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
            if ext in seen:
                continue
            seen.add(ext)
            title = re.sub(r"<[^>]+>", "", inner)
            title = re.sub(r"\s+", " ", title).strip()
            if len(title) < 6:
                continue
            city = self.match_city(title, "江苏")
            notices.append(
                Notice(
                    source_id=self.source_id,
                    source_name=self.source_name,
                    external_id=f"{kind}_{ext}",
                    title=title,
                    province="江苏",
                    city=city,
                    region_text="江苏",
                    keyword=keyword,
                    notice_type=kind,
                    detail_url=url,
                    official_url=url,
                    bid_status="未知",
                    raw={"kind": kind, "login": self._login_state},
                )
            )
        return notices

    def fetch(self, keywords: list[str], *, max_pages: int = 1) -> Iterable[Notice]:
        cfg = sources_cfg().get("jiangsu_zhaobiao") or {}
        if cfg.get("login_required") is not False:
            self.ensure_login()
        # warm home
        try:
            self.http.get_text(HOME, headers={"Referer": HOME})
        except Exception:
            pass

        for kw in keywords:
            for page in range(1, max_pages + 1):
                q = (
                    f"page={page}&attachment=1&channels=&area=&field=all"
                    f"&queryword={quote(kw)}"
                )
                url = f"{HOME}/psearch/Dqsearch?{q}"
                _, raw, _ = self.http.request(url, headers={"Referer": HOME})
                html = _decode_response(raw)
                items = self._parse_list(html, kw)
                for n in items:
                    yield n
                self.http.sleep()
                if not items:
                    break
