from __future__ import annotations

import urllib.parse
from typing import Iterable

from crawl.config_loader import sources_cfg
from crawl.models import Notice
from crawl.sources.base import BaseSource, SourceError


class ChinabiddingSource(BaseSource):
    """中国采购与招标网。接口偶发超时（transient）：按关键词隔离故障，绝不因单个词失败丢弃已采结果。"""

    source_id = "chinabidding"
    source_name = "中国采购与招标网"

    def fetch(self, keywords: list[str], *, max_pages: int = 1) -> Iterable[Notice]:
        cfg = sources_cfg().get("chinabidding") or {}
        api = cfg["list_api"]
        rp = int(cfg.get("rp") or 15)
        host = cfg.get("detail_host") or "https://www.chinabidding.cn"
        headers = {
            "Referer": "https://www.chinabidding.com.cn/search",
            "Accept": "application/json",
        }

        collected: list[Notice] = []
        errors: list[str] = []
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
                try:
                    data = self.http.get_json(url, headers=headers)
                    if not isinstance(data, dict):
                        raise ValueError(f"接口返回非 JSON 对象: {str(data)[:120]}")
                    items = data.get("relatedList") or data.get("list") or []
                except Exception as e:  # noqa: BLE001
                    # 单关键词故障隔离：记录错误、冷却后继续下一个关键词
                    errors.append(f"{kw} p{page}: {str(e)[:160]}")
                    self.http.sleep()
                    continue
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    path = it.get("url") or ""
                    detail = host + path if str(path).startswith("/") else (path or None)
                    title = it.get("title") or ""
                    n = Notice(
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
                    collected.append(n)
                    yield n
                self.http.sleep()
                if not items:
                    break
        if errors:
            detail = "; ".join(errors[:3])[:400]
            if collected:
                print(f"[chinabidding] {len(errors)} 个请求失败但已采 {len(collected)} 条，失败详情: {detail}", flush=True)
            else:
                raise SourceError(f"chinabidding 全部请求失败: {detail}", partial=collected)
