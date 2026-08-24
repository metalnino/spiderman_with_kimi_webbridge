"""乙方宝（yfbzb.com）—— HTTP 级源站（一级探路即通，无需浏览器）。

列表/搜索：GET https://www.yfbzb.com/search/invitedBidSearch?keyword=<kw>&pageNo=<n>
         返回 table#treeTable（公告标题/公告类型/地区/发布时间）。
详情：https://www.yfbzb.com/inviteBid/detail/<YYYYMMDD_<id>>.html（正文/招标人/联系人/电话）。
注意：m.yfbzb.com 移动端 403 拦 IP；www 域正常。
"""
from __future__ import annotations

import re
from html import unescape
from typing import Iterable
from urllib.parse import quote

from crawl.models import Notice
from crawl.sources.base import BaseSource, SourceError

SEARCH_URL = "https://www.yfbzb.com/search/invitedBidSearch"
DETAIL_URL = "https://www.yfbzb.com/inviteBid/detail/{}.html"

_ROW_RE = re.compile(
    r'<a[^>]*href="/inviteBid/detail/(\d{8}_\d+)\.html"[^>]*>(.*?)</a>.*?'
    r'<td class="text-align">([^<]{1,20})</td>\s*'
    r'<td class="text-align">([^<]{1,30})</td>\s*'
    r'<td class="text-align">(20\d{2}-\d{2}-\d{2})</td>',
    re.S,
)


class YfbzbSource(BaseSource):
    source_id = "yfbzb"
    source_name = "乙方宝"

    def _parse_rows(self, html: str, keyword: str) -> list[Notice]:
        notices: list[Notice] = []
        seen: set[str] = set()
        for m in _ROW_RE.finditer(html):
            rid, inner, notice_type, region, pub = m.groups()
            if rid in seen:
                continue
            seen.add(rid)
            title = re.sub(r"<[^>]+>", "", inner)
            title = unescape(re.sub(r"\s+", " ", title)).strip()
            if len(title) < 4:
                continue
            region = unescape(region).strip()
            city = self.match_city((region or "") + " " + title)
            notices.append(
                Notice(
                    source_id=self.source_id,
                    source_name=self.source_name,
                    external_id=rid,
                    title=title,
                    publish_date=pub,
                    city=city,
                    region_text=region,
                    keyword=keyword,
                    notice_type=unescape(notice_type).strip(),
                    detail_url=DETAIL_URL.format(rid),
                    official_url=DETAIL_URL.format(rid),
                    bid_status="未知",
                )
            )
        return notices

    def fetch(self, keywords: list[str], *, max_pages: int = 1) -> Iterable[Notice]:
        cap = self._pages_cap(max_pages, 3)
        for kw in keywords:
            for page in range(1, cap + 1):
                url = f"{SEARCH_URL}?keyword={quote(kw)}&pageNo={page}"
                try:
                    html = self.http.get_text(
                        url,
                        headers={"Referer": "https://www.yfbzb.com/inviteBid/",
                                 "X-Requested-With": "XMLHttpRequest"},
                    )
                except Exception as e:  # noqa: BLE001
                    raise SourceError(f"yfbzb list failed: {str(e)[:200]}") from e
                items = self._parse_rows(html, kw)
                self._count_page()
                if not items:
                    break
                yield from items
                self.http.sleep()
                if self._page_all_seen(items, page):
                    break
