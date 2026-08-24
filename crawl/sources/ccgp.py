from __future__ import annotations

import os
import re
import time
import urllib.parse
from html import unescape
from typing import Iterable

from crawl.config_loader import anti_bot_cfg, sources_cfg
from crawl.models import Notice
from crawl.sources.base import BaseSource, SourceError
from crawl import watermark  # noqa: E402  (P7 水位：整页已见即停)

# 频控页特征：正文含这些字样（页面极短，约 2.7KB）
BLOCK_MARKERS = ("访问过于频繁", "您的访问过于频繁", "频繁访问", "操作频繁")

NOTICE_TYPE_RE = re.compile(
    r"(公开招标公告|竞争性磋商公告|竞争性谈判公告|询价公告|单一来源公告|中标公告|成交公告|更正公告|废标公告|终止公告|其他公告)"
)
REGION_AFTER_TYPE_RE = re.compile(
    r"(?:公开招标|竞争性磋商|竞争性谈判|询价|单一来源|中标|成交|更正|废标|终止|其他)公告?\s*\|\s*([^\s|]*)\s*\|"
)


class CcgpSource(BaseSource):
    """中国政府采购网。频控策略：识别→冷却阶梯重试→仍被拦则保留已采部分结果抛出 SourceError。"""

    source_id = "ccgp"
    source_name = "中国政府采购网"

    # -- 频控配置 ---------------------------------------------------------
    def _block_cfg(self) -> tuple[list[int], int]:
        per = (anti_bot_cfg().get("per_source") or {}).get("ccgp") or {}
        ladder = [int(x) for x in (per.get("block_cooldown_sec") or [90, 180, 300])]
        max_retries = int(per.get("max_block_retries") or len(ladder) or 3)
        # 测试/实网应急可用环境变量缩短冷却阶梯
        env = os.environ.get("CCGP_BLOCK_COOLDOWN_SEC")
        if env:
            ladder = [int(x) for x in env.split(",") if x.strip().isdigit()]
        return ladder, max_retries

    @staticmethod
    def is_blocked(html: str) -> bool:
        if not html:
            return False
        head = html[:3000]
        if any(m in head for m in BLOCK_MARKERS):
            return True
        # 正常结果页几十 KB 起；频控页极短且含「频繁」字样
        return len(html) < 3000 and "频繁" in html

    @staticmethod
    def extract_notice_type(text: str) -> str | None:
        m = NOTICE_TYPE_RE.search(text)
        return m.group(1) if m else None

    @staticmethod
    def extract_region(text: str) -> str | None:
        """行尾「中标公告 | 北京 |」结构中的地区字段（可能是市，也可能是省）。"""
        m = REGION_AFTER_TYPE_RE.search(text)
        if not m:
            return None
        region = m.group(1).strip()
        return region or None

    def city_for(self, title_buyer: str, region: str | None) -> str | None:
        """城市判定：标题/采购人优先；地区字段仅当是目标市名时兜底。
        省份不映射到市（避免把「浙江·金华」误标成杭州的假线索）。"""
        city = self.match_city(title_buyer)
        if city:
            return city
        if not region:
            return None
        base = re.sub(r"(省|市|自治区|特别行政区)$", "", region.strip())
        for c in self.cities:
            if base == c["name"] or base.startswith(c["name"]):
                return c["name"]
        return None

    # -- 单页请求：带冷却阶梯的频控重试 -----------------------------------
    def _fetch_page(self, url: str, collected: list[Notice]) -> str:
        ladder, max_retries = self._block_cfg()
        headers = {"Referer": "https://www.ccgp.gov.cn/", "Accept": "text/html,*/*"}
        for attempt in range(max_retries + 1):
            try:
                html = self.http.get_text(url, headers=headers)
            except Exception as e:  # noqa: BLE001
                raise SourceError(f"ccgp 请求失败: {e}", partial=collected) from e
            if not self.is_blocked(html):
                return html
            if attempt >= max_retries:
                break
            wait = ladder[min(attempt, len(ladder) - 1)]
            print(
                f"[ccgp] 命中频控页，冷却 {wait}s 后重试 ({attempt + 1}/{max_retries + 1})",
                flush=True,
            )
            time.sleep(wait)
        raise SourceError(
            f"ccgp rate_limited（连续 {max_retries + 1} 次请求均被频控，冷却阶梯 {ladder} 已耗尽）",
            partial=collected,
        )

    # -- 主流程 -----------------------------------------------------------
    def fetch(self, keywords: list[str], *, max_pages: int = 1,
              start_time: str | None = None, end_time: str | None = None) -> Iterable[Notice]:
        cfg = sources_cfg().get("ccgp") or {}
        time_type = str(cfg.get("time_type") or "5")
        # P7 召回：ccgp 默认最多扫 SPIDER_CCGP_MAX_PAGES 页（未设则 max(6, max_pages)），
        # 碰到「整页已见」即停（水位边界）——不再永远只扫第一页。
        env_pages = os.environ.get("SPIDER_CCGP_MAX_PAGES")
        pages_cap = int(env_pages) if env_pages and env_pages.strip().isdigit() else max(6, max_pages)
        self.last_scanned_pages = 0
        collected: list[Notice] = []
        for kw in keywords:
            for page in range(1, pages_cap + 1):
                q = urllib.parse.urlencode(
                    {
                        "searchtype": "1",
                        "page_index": str(page),
                        "bidSort": "0",
                        "buyerName": "",
                        "projectId": "",
                        "pinMu": "0",
                        "bidType": "0",
                        "dbselect": "bidx",
                        "kw": kw,
                        "timeType": time_type,
                        **({"start_time": start_time} if start_time else {}),
                        **({"end_time": end_time} if end_time else {}),
                    }
                )
                url = "https://search.ccgp.gov.cn/bxsearch?" + q
                html = self._fetch_page(url, collected)
                items = self._parse(html, kw)
                self.last_scanned_pages += 1
                if not items and "cggg/" in html:
                    # 页面有结果链接但解析为 0 → 版面变化预警，绝不静默当「无结果」
                    print("[ccgp] WARN: 页面含结果链接但解析为 0 条，疑似版面变化", flush=True)
                for n in items:
                    collected.append(n)
                    yield n
                self.http.sleep()
                if not items:
                    # 该词无结果或结果尽：不再翻页
                    break
                if self._page_all_seen(items, page):
                    # 水位边界（且历史曾扫得更深）：更深页不再扫
                    break

    def _parse(self, html: str, kw: str) -> list[Notice]:
        out: list[Notice] = []
        blocks = re.split(r"<li\b", html, flags=re.I)
        seen = set()
        for block in blocks[1:]:
            link = re.search(
                r'href="(https?://www\.ccgp\.gov\.cn/cggg/[^"]+\.htm)"[^>]*>(.*?)</a>',
                block,
                re.I | re.S,
            )
            if not link:
                continue
            href = link.group(1).replace("http://", "https://")
            if href in seen:
                continue
            seen.add(href)
            title = re.sub(r"<[^>]+>", "", link.group(2))
            title = re.sub(r"\s+", " ", unescape(title)).strip()
            if len(title) < 4:
                continue
            text = re.sub(r"<[^>]+>", " ", block)
            text = re.sub(r"\s+", " ", unescape(text))
            pub = None
            mp = re.search(r"(20\d{2}\.\d{2}\.\d{2}\s+\d{2}:\d{2}:\d{2})", text)
            if mp:
                pub = mp.group(1).replace(".", "-")
            buyer = None
            mb = re.search(r"采购人[：:]\s*([^|]+)", text)
            if mb:
                buyer = mb.group(1).strip()[:80]
            agency = None
            ma = re.search(r"代理机构[：:]\s*([^|]+)", text)
            if ma:
                agency = ma.group(1).strip()[:80]
            region = self.extract_region(text)
            city = self.city_for((buyer or "") + " " + title, region)
            notice_type = self.extract_notice_type(text)
            # external from url filename
            m_id = re.search(r"t(\d+)_\d+\.htm", href)
            ext = m_id.group(1) if m_id else href
            out.append(
                Notice(
                    source_id=self.source_id,
                    source_name=self.source_name,
                    external_id=str(ext),
                    title=title,
                    publish_date=pub,
                    city=city,
                    region_text=region,
                    keyword=kw,
                    buyer=buyer,
                    agency=agency,
                    notice_type=notice_type,
                    detail_url=href,
                    bid_status="未知",
                )
            )
        return out
