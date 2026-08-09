from __future__ import annotations

import re
import time
import urllib.parse
from html import unescape
from typing import Iterable

from crawl.config_loader import crawl_cfg
from crawl.models import Notice
from crawl.sources.base import BaseSource

LIST_URL = "https://bulletin.cebpubservice.com/xxfbcmses/search/bulletin.html"


class CebpubSource(BaseSource):
    source_id = "cebpub"
    source_name = "中国招标投标公共服务平台"

    def fetch(self, keywords: list[str], *, max_pages: int = 1) -> Iterable[Notice]:
        cfg = crawl_cfg()
        src = cfg.get("source") or {}
        category_id = src.get("category_id") or "88"
        dates = src.get("dates") or "300"
        # P0：全国关键词检索（area 空），城市靠标题匹配；控制请求量
        for kw in keywords:
            for page in range(1, max_pages + 1):
                q = {
                    "searchDate": time.strftime("%Y-%m-%d"),
                    "dates": dates,
                    "word": kw,
                    "categoryId": category_id,
                    "industryName": "",
                    "area": "",
                    "status": "",
                    "publishMedia": "",
                    "sourceInfo": "",
                    "showStatus": src.get("show_status") or "1",
                    "page": str(page),
                }
                url = LIST_URL + "?" + urllib.parse.urlencode(q)
                html = self.http.get_text(url, headers={"Accept": "text/html,*/*"})
                pattern = re.compile(
                    r"<a[^>]*href=\"javascript:urlOpen\('([0-9a-fA-F]{16,})'\)\"[^>]*>(.*?)</a>",
                    re.I | re.S,
                )
                for uuid, inner in pattern.findall(html):
                    title = re.sub(r"<[^>]+>", "", inner)
                    title = re.sub(r"\s+", " ", unescape(title)).strip()
                    if len(title) < 4:
                        continue
                    city = self.match_city(title)
                    detail = (
                        "https://ctbpsp.com/#/bulletinDetail?uuid="
                        f"{uuid}&inpvalue=&dataSource=0&tenderAgency="
                    )
                    yield Notice(
                        source_id=self.source_id,
                        source_name=self.source_name,
                        external_id=uuid,
                        title=title,
                        city=city,
                        keyword=kw,
                        detail_url=detail,
                        official_url=detail,
                        bid_status="未知",
                        raw={"area": ""},
                    )
                self.http.sleep()
