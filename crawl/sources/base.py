from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Iterable

from crawl.config_loader import cities
from crawl.http_session import HttpSession
from crawl.models import Notice
from crawl import watermark  # noqa: E402  (P7 水位：整页已见即停/页数上报)


class SourceError(Exception):
    """源站级失败。partial 携带失败前已采集的公告，调用方必须入库而不是丢弃。"""

    def __init__(self, message: str, partial: Iterable[Notice] | None = None):
        super().__init__(message)
        self.partial: list[Notice] = list(partial or [])


class BaseSource(ABC):
    source_id: str
    source_name: str

    def __init__(self):
        self.http = HttpSession(self.source_id)
        self.cities = cities()
        self.last_scanned_pages = 0

    def match_city(self, title: str, province: str | None = None) -> str | None:
        hits = [c["name"] for c in self.cities if c["name"] in (title or "")]
        if province == "上海" and "上海" not in hits:
            return "上海"
        return hits[0] if hits else None

    # -- P7 召回自证助手 ---------------------------------------------------
    def _pages_cap(self, max_pages: int, default: int) -> int:
        """每站页数上限：SPIDER_<SID>_MAX_PAGES 环境变量 > 调用方 max_pages > 默认值取大。"""
        env = os.environ.get(f"SPIDER_{self.source_id.upper()}_MAX_PAGES")
        if env and env.strip().isdigit():
            return int(env)
        return max(max_pages, default)

    def _wm_seen(self) -> set[str]:
        return watermark.load(self.source_id)

    def _page_all_seen(self, notices: list, page: int = 1) -> bool:
        """整页原始 external_id 全部已见 **且历史曾扫得更深** → 边界可信，更深页不再扫。

        冷启动保护：水位只来自第 1 页时（last_scan_pages ≤ 当前页），第 2+ 页可能从未见过，
        「整页已见→更深页更旧」不成立，必须继续翻到空/上限。
        """
        wm = self._wm_seen()
        if not (wm and notices and all(getattr(n, "external_id", None) in wm for n in notices)):
            return False
        last = watermark.get_last_pages(self.source_id) or 0
        return last > page

    def _count_page(self) -> None:
        self.last_scanned_pages += 1

    @abstractmethod
    def fetch(self, keywords: list[str], *, max_pages: int = 1) -> Iterable[Notice]:
        raise NotImplementedError
