from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from crawl.config_loader import cities
from crawl.http_session import HttpSession
from crawl.models import Notice


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

    def match_city(self, title: str, province: str | None = None) -> str | None:
        hits = [c["name"] for c in self.cities if c["name"] in (title or "")]
        if province == "上海" and "上海" not in hits:
            return "上海"
        return hits[0] if hits else None

    @abstractmethod
    def fetch(self, keywords: list[str], *, max_pages: int = 1) -> Iterable[Notice]:
        raise NotImplementedError
