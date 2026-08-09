from __future__ import annotations

import random
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from typing import Optional

from crawl.config_loader import anti_bot_cfg

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


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
        if headers:
            hdrs.update(headers)
        last: Exception | None = None
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
            except Exception as e:  # noqa: BLE001
                last = e
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
