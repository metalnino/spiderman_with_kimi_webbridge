"""深圳阳光采购平台（ygcg.szexgrp.com）—— HTTP JSON API 直调（无登录/无验证码/无 WAF）。

列表：POST https://ygcg.szexgrp.com/api/v1/trade/content/page
      body: {channelId:4161, fields:null, title:<kw>, page:<0-based>, size:20, siteId:216, ...}
      （fields=null → 返回全部公告类型；传 [{fieldName:"jygg_gglxmc",fieldValue:"采购公告"}] 则按类型筛）
返回：{code:200, data:{content:[{title, bidSectionNumber, noticeTypeCode, noticeTypeName,
                                releaseTime, id, ...}], totalElements}}
详情：/jyxxDetails.htm?bidSectionNumber=<n>&contentId=<id>&code=<noticeTypeCode 末段>（JS 壳，正文另经接口/桥）。

平台即深圳交易集团，故 city 固定 = 深圳（8 城目标之一）。
"""
from __future__ import annotations

import json
import urllib.parse
from datetime import datetime, timedelta
from typing import Iterable

from crawl.config_loader import sources_cfg
from crawl.models import Notice
from crawl.sources.base import BaseSource, SourceError

BASE = "https://ygcg.szexgrp.com"
API = BASE + "/api/v1/trade/content/page"

# 只收「公开采购全周期」的公告类型；邀请函(邀请投标,非公开)、合同续期公示(已成交续签)、其他公示 与我们无关。
DEFAULT_NOTICE_TYPES = ("采购公告", "变更公示", "候选人公示", "结果公示", "定标结果公示")


class SzexgrpSource(BaseSource):
    """深圳阳光采购平台。HTTP API 直调，无登录/验证码。"""

    source_id = "szexgrp"
    source_name = "深圳阳光采购平台"

    def _detail_url(self, rec: dict) -> str | None:
        link = rec.get("linkTo")
        if link:
            s = str(link)
            return s if s.startswith("http") else BASE + s
        bid = str(rec.get("bidSectionNumber") or "").strip()
        cid = rec.get("id") or rec.get("contentId")
        if not (bid and cid):
            return None
        code = str(rec.get("noticeTypeCode") or "").split("_")[-1]
        return (f"{BASE}/jyxxDetails.htm?bidSectionNumber={urllib.parse.quote(bid)}"
                f"&contentId={cid}&code={urllib.parse.quote(code)}")

    def _page(self, kw: str, page: int, size: int,
              begin_ms: int | None = None, end_ms: int | None = None) -> list[dict]:
        body = {
            "channelId": 4161,
            "fields": None,  # None = 全部公告类型；类型白名单在客户端按 noticeTypeName 过滤
            "title": kw,
            "bidSectionNumber": "",
            "purchaseCom": "",
            # 服务端时间过滤（毫秒时间戳，实测有效）：把 1149 条压到 75 条/30天，少翻页少脏数据
            "releaseTimeBegin": begin_ms,
            "releaseTimeEnd": end_ms,
            "siteId": 216,
            "page": page - 1,  # 接口 page 从 0 开始
            "size": size,
            "keyword": "",
        }
        try:
            data = self.http.get_json(
                API,
                data=json.dumps(body).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Referer": BASE + "/jyxx",
                    "Origin": BASE,
                    "Accept": "application/json, text/plain, */*",
                },
            )
        except Exception as e:  # noqa: BLE001
            raise SourceError(f"szexgrp 列表请求失败: {str(e)[:200]}") from e
        if not isinstance(data, dict) or data.get("code") != 200:
            raise SourceError(f"szexgrp code={data.get('code') if isinstance(data, dict) else '?'} {data.get('msg') if isinstance(data, dict) else ''}")
        return ((data.get("data") or {}).get("content")) or []

    def fetch(self, keywords: list[str], *, max_pages: int = 1) -> Iterable[Notice]:
        cfg = sources_cfg().get("szexgrp") or {}
        size = int(cfg.get("page_size") or 20)
        include_types = {str(t).strip() for t in (cfg.get("notice_types") or DEFAULT_NOTICE_TYPES) if str(t).strip()}
        release_days = int(cfg.get("release_days") or 0)
        begin_ms = end_ms = None
        if release_days > 0:
            now = datetime.now()
            begin_ms = int((now - timedelta(days=release_days)).timestamp() * 1000)
            end_ms = int(now.timestamp() * 1000)
        cap = self._pages_cap(max_pages, 3)
        for kw in keywords:
            for page in range(1, cap + 1):
                recs = self._page(kw, page, size, begin_ms, end_ms)
                page_notices: list[Notice] = []
                for rec in recs:
                    if not isinstance(rec, dict):
                        continue
                    ntype = (rec.get("noticeTypeName") or "").strip()
                    # 类型白名单：邀请函(邀请投标)/合同续期公示/其他公示 等与「公开招标」无关，直接丢
                    if include_types and ntype and ntype not in include_types:
                        continue
                    title = (rec.get("noticeTitle") or rec.get("title") or "").strip()
                    if len(title) < 4:
                        continue
                    cid = rec.get("id") or rec.get("contentId")
                    page_notices.append(Notice(
                        source_id=self.source_id,
                        source_name=self.source_name,
                        external_id=str(cid or ""),
                        title=title,
                        publish_date=(rec.get("releaseTime") or None),
                        city="深圳",  # 平台即深圳
                        province="广东",
                        region_text=(rec.get("areaName") or "深圳"),
                        keyword=kw,
                        notice_type=(rec.get("noticeTypeName") or None),
                        detail_url=self._detail_url(rec),
                        project_code=(rec.get("bidSectionNumber") or None),
                        bid_status="未知",
                        raw={"noticeTypeCode": rec.get("noticeTypeCode"), "noticeId": rec.get("noticeId")},
                    ))
                self._count_page()
                yield from page_notices
                self.http.sleep()
                if not recs:
                    break
                if self._page_all_seen(page_notices, page):
                    break
