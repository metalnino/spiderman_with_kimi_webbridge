"""千里马招标网（qianlima.com）—— HTTP 级源站（搜索 JSON API 直调，一级即通）。

列表：POST https://search.qianlima.com/api/v1/website/search
      query: filtermode=1&timeType=101&areas=&types=-1&searchMode=0&keywords=<kw>
             &beginTime=&endTime=&isfirst=true&currentPage=<n>&numPerPage=20
      （空 body + Referer，实测纯 HTTP 直调成功）
返回 JSON：data.data[] {contentid, popTitle, showTitle, updateTime, areaName, progName, url, originUrl}
详情：https://www.qianlima.com/bid-<contentid>.html（HTTP 419 反爬 → 详情走桥，
      列表字段已含标题/地区/时间/阶段，可无详情运行）。
"""
from __future__ import annotations

import json
from typing import Iterable
from urllib.parse import quote

from crawl.models import Notice
from crawl.sources.base import BaseSource, SourceError

SEARCH_API = "https://search.qianlima.com/api/v1/website/search"
DETAIL_URL = "https://www.qianlima.com/bid-{}.html"


class QianlimaSource(BaseSource):
    source_id = "qianlima"
    source_name = "千里马招标网"

    def _build_url(self, kw: str, page: int) -> str:
        return (
            f"{SEARCH_API}?filtermode=1&timeType=101&areas=&types=-1&searchMode=0"
            f"&keywords={quote(kw)}&beginTime=&endTime=&isfirst=true"
            f"&currentPage={page}&numPerPage=20"
        )

    def _parse(self, data: dict, keyword: str) -> list[Notice]:
        records = ((data.get("data") or {}).get("data")) or []
        notices: list[Notice] = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            cid = str(rec.get("contentid") or "")
            if not cid:
                continue
            title = (rec.get("popTitle") or rec.get("showTitle") or "").strip()
            if len(title) < 4:
                continue
            area = (rec.get("areaName") or "").strip()  # 形如 "上海-上海" / "四川-成都"
            city = self.match_city((area or "") + " " + title)
            notices.append(
                Notice(
                    source_id=self.source_id,
                    source_name=self.source_name,
                    external_id=cid,
                    title=title,
                    publish_date=(rec.get("updateTime") or None),
                    city=city,
                    region_text=area,
                    keyword=keyword,
                    notice_type=(rec.get("progName") or None),
                    detail_url=DETAIL_URL.format(cid),
                    official_url=(rec.get("originUrl") or None),
                    bid_status="未知",
                )
            )
        return notices

    def fetch(self, keywords: list[str], *, max_pages: int = 1) -> Iterable[Notice]:
        cap = self._pages_cap(max_pages, 3)
        for kw in keywords:
            for page in range(1, cap + 1):
                try:
                    _, raw, _ = self.http.request(
                        self._build_url(kw, page),
                        data=b"",
                        headers={
                            "Referer": f"https://search.qianlima.com/?q={quote(kw)}",
                            "Accept": "application/json, text/plain, */*",
                            "Content-Type": "application/json",
                        },
                    )
                    data = json.loads(raw.decode("utf-8", "ignore"))
                except Exception as e:  # noqa: BLE001
                    raise SourceError(f"qianlima search failed: {str(e)[:200]}") from e
                if not isinstance(data, dict) or str(data.get("code")) != "200":
                    raise SourceError(f"qianlima api code={data.get('code')} msg={data.get('msg')}")
                items = self._parse(data, kw)
                self._count_page()
                if not items:
                    break
                yield from items
                self.http.sleep()
                if self._page_all_seen(items):
                    break
