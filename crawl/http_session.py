from __future__ import annotations

import random
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from typing import Optional

from crawl.config_loader import anti_bot_cfg, proxy_for
from crawl import cookie_store
from crawl.jsl_clearance import try_solve_521
from crawl.warm_session import WARM_URLS

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _http_error_label(e: urllib.error.HTTPError) -> str:
    code = e.code
    if code == 429:
        return "rate_limited(HTTP 429)"
    if code == 403:
        return "rate_limited_or_blocked(HTTP 403)"
    if code == 521:
        return "origin_down(HTTP 521)"
    return f"HTTP {code}"


class HttpSession:
    """HTTP with optional cookie jar + jitter delays (anti_bot)."""

    def __init__(self, source_id: str | None = None):
        self.source_id = source_id
        self.cj = CookieJar()
        self.proxy = proxy_for(source_id)  # 配置错误（非法 scheme）在此响亮报错，不静默直连
        handlers: list = [urllib.request.HTTPCookieProcessor(self.cj)]
        if self.proxy:
            handlers.insert(0, urllib.request.ProxyHandler({"http": self.proxy, "https": self.proxy}))
        else:
            # 未配置 per-source 代理时必须显式直连，绝不跟随系统代理（否则 Clash 系统代理会拖慢全部"直连"源站）
            handlers.insert(0, urllib.request.ProxyHandler({}))
        self.opener = urllib.request.build_opener(*handlers)
        ab = anti_bot_cfg()
        http = ab.get("http") or {}
        per = ((ab.get("per_source") or {}).get(source_id or "") or {})
        self.timeout = int(per.get("timeout_sec") or http.get("timeout_sec") or 40)
        self.retries = int(per.get("retries") or http.get("retries") or 3)
        self.delay_min = int(per.get("delay_ms_min") or http.get("delay_ms_min") or 800) / 1000
        self.delay_max = int(per.get("delay_ms_max") or http.get("delay_ms_max") or 2200) / 1000
        self.backoff_429 = float(per.get("backoff_429_sec") or http.get("backoff_429_sec") or 20)
        self.backoff_base = float(per.get("backoff_base_sec") or http.get("backoff_base_sec") or 1.5)
        self.jsl_clearance = bool(per.get("jsl_clearance") or source_id == "jiangsu_zhaobiao")
        self._cookie_header: str | None = None
        if source_id:
            self.load_stored_cookies(source_id)

    def load_stored_cookies(self, source_id: str) -> int:
        hdr = cookie_store.cookie_header(source_id)
        if not hdr:
            return 0
        self._cookie_header = hdr
        url = WARM_URLS.get(source_id) or "https://example.com/"
        return cookie_store.apply_to_jar(self.cj, hdr, url)

    def sleep(self):
        time.sleep(random.uniform(self.delay_min, self.delay_max))

    def request(
        self,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict | None = None,
        method: str | None = None,
    ) -> tuple[int, bytes, str]:
        hdrs = {"User-Agent": UA, "Accept": "*/*"}
        if self._cookie_header and "Cookie" not in (headers or {}):
            hdrs["Cookie"] = self._cookie_header
        if headers:
            hdrs.update(headers)
        last: str | None = None
        for i in range(self.retries):
            try:
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers=hdrs,
                    method=method or ("POST" if data else "GET"),
                )
                with self.opener.open(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    final = resp.geturl()
                    return resp.status, raw, final
            except urllib.error.HTTPError as e:
                last = _http_error_label(e)
                body = b""
                try:
                    body = e.read()
                except Exception:
                    body = b""
                # 江苏站等 CDN：先解一层 __jsl_clearance_s，再重试
                if self.jsl_clearance and e.code == 521 and body:
                    html = body.decode("utf-8", "ignore")
                    if try_solve_521(html, self.cj, url):
                        # 同步 header，后续请求带上 jar
                        bits = [f"{c.name}={c.value}" for c in self.cj]
                        if bits:
                            self._cookie_header = "; ".join(bits)
                            hdrs["Cookie"] = self._cookie_header
                        time.sleep(0.3)
                        continue
                if e.code == 429:
                    # 频控：冷却后重试（冷却时间随次数线性增长 + 抖动）
                    time.sleep(self.backoff_429 * (i + 1) + random.uniform(0, 5))
                    continue
                if e.code == 403:
                    # 疑似频控/风控：短退避后有限重试
                    time.sleep(self.backoff_base * (i + 1) + random.uniform(0, 2))
                    continue
                if e.code == 408:
                    time.sleep(self.backoff_base * (i + 1))
                    continue
                if 400 <= e.code < 500:
                    break
                # 5xx/源站瞬断：指数退避（封顶 16s）+ 抖动
                time.sleep(min(self.backoff_base * (2**i), 16) + random.uniform(0, 1))
            except Exception as e:  # noqa: BLE001
                last = str(e) or type(e).__name__
                time.sleep(min(self.backoff_base * (2**i), 16) + random.uniform(0, 1))
        raise RuntimeError(f"http failed: {url} ({last})")

    def get_text(self, url: str, *, headers: dict | None = None, encoding_hint: Optional[str] = None) -> str:
        _, raw, _ = self.request(url, headers=headers)
        if encoding_hint:
            return raw.decode(encoding_hint, "ignore")
        for enc in ("utf-8", "gbk", "gb2312"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", "ignore")

    def get_json(self, url: str, *, headers: dict | None = None, data: bytes | None = None):
        import json

        _, raw, _ = self.request(url, headers=headers, data=data)
        return json.loads(raw.decode("utf-8", "ignore"))
