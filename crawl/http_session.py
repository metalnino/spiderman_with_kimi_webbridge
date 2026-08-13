from __future__ import annotations

import random
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from typing import Optional

from crawl.config_loader import anti_bot_cfg
from crawl import cookie_store
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
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        ab = anti_bot_cfg()
        http = ab.get("http") or {}
        per = ((ab.get("per_source") or {}).get(source_id or "") or {})
        self.timeout = int(http.get("timeout_sec") or 20)
        self.retries = int(http.get("retries") or 2)
        self.delay_min = int(per.get("delay_ms_min") or http.get("delay_ms_min") or 800) / 1000
        self.delay_max = int(per.get("delay_ms_max") or http.get("delay_ms_max") or 2200) / 1000
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
                # 4xx 客户端错误通常重试无益；立即失败，交由上层按状态归类
                if 400 <= e.code < 500:
                    break
                time.sleep(0.5 * (i + 1))
            except Exception as e:  # noqa: BLE001
                last = str(e) or type(e).__name__
                time.sleep(0.5 * (i + 1))
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
