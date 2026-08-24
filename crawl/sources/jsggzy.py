"""江苏省公共资源交易网 / 江苏切片。

主路径：全国 ggzy + DEAL_PROVINCE=320000（稳定可测）
辅路径：省站 inteligentsearch（HTTP/跳过坏证书），失败不阻断。
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Iterable

from crawl.config_loader import sources_cfg
from crawl.models import Notice
from crawl.sources.base import BaseSource

CTX = ssl._create_unverified_context()
PROVINCE_CODE = "320000"


class JsggzySource(BaseSource):
    source_id = "jsggzy"
    source_name = "江苏省公共资源交易网"

    def fetch(self, keywords: list[str], *, max_pages: int = 1) -> Iterable[Notice]:
        seen = set()
        for kw in keywords:
            for n in self._fetch_via_national(kw, max_pages):
                if n.external_id in seen:
                    continue
                seen.add(n.external_id)
                yield n
            # best-effort provincial API
            try:
                for n in self._fetch_via_province_api(kw, max_pages):
                    if n.external_id in seen:
                        continue
                    seen.add(n.external_id)
                    yield n
            except Exception:
                pass
            self.http.sleep()

    def _fetch_via_national(self, kw: str, max_pages: int) -> list[Notice]:
        cfg = sources_cfg().get("ggzy") or {}
        api = cfg.get("api") or "https://www.ggzy.gov.cn/information/pubTradingInfo/getTradList"
        deal_time = str(cfg.get("deal_time") or "05")
        referer = cfg.get("referer") or "https://www.ggzy.gov.cn/deal/dealList.html"
        cap = self._pages_cap(max_pages, 3)
        out: list[Notice] = []
        for page in range(1, cap + 1):
            body = urllib.parse.urlencode(
                {
                    "FINDTXT": kw,
                    "PAGENUMBER": str(page),
                    "DEAL_TIME": deal_time,
                    "DEAL_PROVINCE": PROVINCE_CODE,
                }
            ).encode()
            data = self.http.get_json(
                api,
                data=body,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Referer": referer,
                    "Origin": "https://www.ggzy.gov.cn",
                },
            )
            if data.get("code") != 200:
                break
            recs = ((data.get("data") or {}).get("records")) or []
            page_notices: list[Notice] = []
            for rec in recs:
                href = rec.get("url") or ""
                detail = ("https://www.ggzy.gov.cn" + href) if str(href).startswith("/") else href
                title = rec.get("title") or ""
                page_notices.append(
                    Notice(
                        source_id=self.source_id,
                        source_name=self.source_name,
                        external_id=f"js-{rec.get('id')}",
                        title=title,
                        publish_date=rec.get("publishTime"),
                        province="江苏",
                        city=self.match_city(title, "江苏") or self.match_city(title, "上海"),
                        region_text=rec.get("cityText") or rec.get("provinceText") or "江苏",
                        keyword=kw,
                        notice_type=rec.get("informationTypeText"),
                        detail_url=detail or None,
                        raw={"via": "ggzy_province_slice", "id": rec.get("id")},
                    )
                )
            self._count_page()
            out.extend(page_notices)
            self.http.sleep()
            if not recs:
                break
            if self._page_all_seen(page_notices, page):
                break
        return out

    def _fetch_via_province_api(self, kw: str, max_pages: int) -> list[Notice]:
        cfg = sources_cfg().get("jsggzy") or {}
        api = cfg.get("search_api") or (
            "http://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew"
        )
        out: list[Notice] = []
        for page in range(max_pages):
            payload = {
                "token": "",
                "pn": page * 10,
                "rn": 10,
                "wd": kw,
                "fields": "title",
                "cnum": "001",
                "sort": '{"webdate":"0"}',
                "ssort": "title",
                "cl": 200,
                "highlights": "title",
                "noParticiple": "0",
            }
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                api,
                data=body,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Content-Type": "application/json;charset=UTF-8",
                    "Referer": "http://jsggzy.jszwfw.gov.cn/jyxx/tradeInfonew.html",
                },
            )
            with urllib.request.urlopen(req, timeout=25, context=CTX) as resp:
                raw = resp.read().decode("utf-8", "ignore")
            data = json.loads(raw)
            result = data.get("result") or data.get("data") or {}
            records = result.get("records") or result.get("list") or data.get("records") or []
            if not isinstance(records, list):
                break
            for rec in records:
                if not isinstance(rec, dict):
                    continue
                title = rec.get("title") or rec.get("name") or ""
                title = re_strip_html(title)
                rid = str(rec.get("id") or rec.get("linkurl") or title)[:80]
                link = rec.get("linkurl") or rec.get("url") or ""
                if link and link.startswith("/"):
                    link = "http://jsggzy.jszwfw.gov.cn" + link
                out.append(
                    Notice(
                        source_id=self.source_id,
                        source_name=self.source_name,
                        external_id=f"jsggzy-{rid}",
                        title=title,
                        publish_date=(rec.get("webdate") or rec.get("publishTime") or "")[:19],
                        province="江苏",
                        city=self.match_city(title, "江苏"),
                        keyword=kw,
                        detail_url=link or None,
                        raw={"via": "jsggzy_api"},
                    )
                )
            if not records:
                break
        return out


def re_strip_html(s: str) -> str:
    import re
    from html import unescape

    return re.sub(r"<[^>]+>", "", unescape(s or "")).strip()
