from __future__ import annotations

import re
import urllib.parse
from html import unescape
from typing import Iterable

from crawl.config_loader import sources_cfg
from crawl.models import Notice
from crawl.sources.base import BaseSource


class CcgpSource(BaseSource):
    source_id = "ccgp"
    source_name = "中国政府采购网"

    def fetch(self, keywords: list[str], *, max_pages: int = 1) -> Iterable[Notice]:
        cfg = sources_cfg().get("ccgp") or {}
        time_type = str(cfg.get("time_type") or "5")
        for kw in keywords:
            for page in range(1, max_pages + 1):
                q = urllib.parse.urlencode(
                    {
                        "searchtype": "1",
                        "page_index": str(page),
                        "bidSort": "0",
                        "buyerName": "",
                        "projectId": "",
                        "pinMu": "0",
                        "bidType": "0",
                        "dbselect": "bidx",
                        "kw": kw,
                        "timeType": time_type,
                    }
                )
                url = "https://search.ccgp.gov.cn/bxsearch?" + q
                html = self.http.get_text(
                    url,
                    headers={"Referer": "https://www.ccgp.gov.cn/", "Accept": "text/html,*/*"},
                )
                if "访问过于频繁" in html or "频繁访问" in html:
                    raise RuntimeError("ccgp rate_limited")
                for n in self._parse(html, kw):
                    yield n
                self.http.sleep()

    def _parse(self, html: str, kw: str) -> list[Notice]:
        out: list[Notice] = []
        blocks = re.split(r"<li\b", html, flags=re.I)
        seen = set()
        for block in blocks[1:]:
            link = re.search(
                r'href="(https?://www\.ccgp\.gov\.cn/cggg/[^"]+\.htm)"[^>]*>(.*?)</a>',
                block,
                re.I | re.S,
            )
            if not link:
                continue
            href = link.group(1).replace("http://", "https://")
            if href in seen:
                continue
            seen.add(href)
            title = re.sub(r"<[^>]+>", "", link.group(2))
            title = re.sub(r"\s+", " ", unescape(title)).strip()
            if len(title) < 4:
                continue
            text = re.sub(r"<[^>]+>", " ", block)
            text = re.sub(r"\s+", " ", unescape(text))
            pub = None
            mp = re.search(r"(20\d{2}\.\d{2}\.\d{2}\s+\d{2}:\d{2}:\d{2})", text)
            if mp:
                pub = mp.group(1).replace(".", "-")
            buyer = None
            mb = re.search(r"采购人[：:]\s*([^|]+)", text)
            if mb:
                buyer = mb.group(1).strip()[:80]
            # external from url filename
            m_id = re.search(r"t(\d+)_\d+\.htm", href)
            ext = m_id.group(1) if m_id else href
            out.append(
                Notice(
                    source_id=self.source_id,
                    source_name=self.source_name,
                    external_id=str(ext),
                    title=title,
                    publish_date=pub,
                    city=self.match_city((buyer or "") + " " + title),
                    keyword=kw,
                    buyer=buyer,
                    detail_url=href,
                    bid_status="未知",
                )
            )
        return out
