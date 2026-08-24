"""工程帮（天工网）占位源站——列表走 Playwright 路由（scripts/crawl_tgnet_pw.py），本类仅为注册表占位。"""
from __future__ import annotations

from typing import Iterable

from crawl.models import Notice
from crawl.sources.base import BaseSource, SourceError


class TgnetSource(BaseSource):
    source_id = "tgnet"
    source_name = "工程帮(天工网)"

    def fetch(self, keywords: list[str], *, max_pages: int = 1) -> Iterable[Notice]:
        raise SourceError(
            "tgnet uses playwright route (scripts/crawl_tgnet_pw.main)；"
            "请经采集员外壳 BROWSER_ROUTES 调用，勿直连内核"
        )
