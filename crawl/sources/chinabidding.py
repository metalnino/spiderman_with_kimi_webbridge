from __future__ import annotations

import urllib.parse
from typing import Iterable

from crawl.config_loader import sources_cfg
from crawl.models import Notice
from crawl.sources.base import BaseSource


class ChinabiddingSource(BaseSource):
    source_id = "chinabidding"
    source_name = "中国采购与招标网"

    def fetch(self, keywords: list[str], *, max_pages: int = 1) -> Iterable[Notice]:
        cfg = sources_cfg().get("chinabidding") or {}
        api = cfg["list_api"]
        rp = int(cfg.get("rp") or 15)
        host = cfg.get("detail_host") or "https://www.chinabidding.cn"

        for kw in keywords:
            for page in range(1, max_pages + 1):
                q = urllib.parse.urlencode(
                    {
                        "keyword": kw,
                        "page": str(page),
                        "rp": str(rp),
                        "device": "zbdt001",
                        "cpcode": "zbdt001",
                    }
                )
                url = f"{api}?{q}"
                data = self.http.get_json(
                    url,
                    headers={
                        "Referer": "https://www.chinabidding.com.cn/search",
                        "Accept": "application/json",
                    },
                )
                items = data.get("relatedList") or data.get("list") or []
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    path = it.get("url") or ""
                    detail = host + path if str(path).startswith("/") else (path or None)
                    title = it.get("title") or ""
                    yield Notice(
                        source_id=self.source_id,
                        source_name=self.source_name,
                        external_id=str(it.get("id") or ""),
                        title=title,
                        publish_date=(it.get("publish_date") or "")[:19],
                        city=self.match_city(title),
                        region_text=str(it.get("area_id") or ""),
                        keyword=kw,
                        notice_type=it.get("table_name2"),
                        detail_url=detail,
                        bid_status="未知",
                        raw={"area_id": it.get("area_id"), "table_name": it.get("table_name")},
                    )
                self.http.sleep()
                if not items:
                    break
