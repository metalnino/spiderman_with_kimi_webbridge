from __future__ import annotations

import urllib.parse
from typing import Iterable

from crawl.config_loader import sources_cfg
from crawl.models import Notice
from crawl.sources.base import BaseSource


class GgzySource(BaseSource):
    source_id = "ggzy"
    source_name = "全国公共资源交易平台"

    def fetch(self, keywords: list[str], *, max_pages: int = 1) -> Iterable[Notice]:
        cfg = (sources_cfg().get("ggzy") or {})
        api = cfg.get("api") or "https://www.ggzy.gov.cn/information/pubTradingInfo/getTradList"
        deal_time = str(cfg.get("deal_time") or "05")
        referer = cfg.get("referer") or "https://www.ggzy.gov.cn/deal/dealList.html"
        code_to_prov = {c["area_code"]: c["province"] for c in self.cities}
        cap = self._pages_cap(max_pages, 3)

        for kw in keywords:
            for page in range(1, cap + 1):
                body = urllib.parse.urlencode(
                    {"FINDTXT": kw, "PAGENUMBER": str(page), "DEAL_TIME": deal_time}
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
                if data.get("code") == 829:
                    raise RuntimeError("ggzy captcha_829")
                if data.get("code") != 200:
                    raise RuntimeError(f"ggzy code={data.get('code')} {data.get('message')}")
                recs = ((data.get("data") or {}).get("records")) or []
                page_notices: list[Notice] = []
                for rec in recs:
                    href = rec.get("url") or ""
                    detail = ("https://www.ggzy.gov.cn" + href) if href.startswith("/") else href
                    pcode = str(rec.get("province") or "")
                    prov = code_to_prov.get(pcode) or (rec.get("provinceText") or "").replace("省", "")
                    title = rec.get("title") or ""
                    page_notices.append(Notice(
                        source_id=self.source_id,
                        source_name=self.source_name,
                        external_id=str(rec.get("id") or ""),
                        title=title,
                        publish_date=rec.get("publishTime"),
                        province=prov,
                        city=self.match_city(title, prov),
                        region_text=rec.get("cityText") or rec.get("provinceText"),
                        keyword=kw,
                        notice_type=rec.get("informationTypeText"),
                        detail_url=detail or None,
                        project_code=rec.get("tenderProjectCode"),
                        buyer=None,
                        raw={"id": rec.get("id"), "platform": rec.get("transactionSourcesPlatformText")},
                    ))
                self._count_page()
                yield from page_notices
                self.http.sleep()
                if not recs:
                    break
                if self._page_all_seen(page_notices):
                    break
