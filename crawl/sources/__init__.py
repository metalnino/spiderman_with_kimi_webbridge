from crawl.sources.cebpub import CebpubSource
from crawl.sources.chinabidding import ChinabiddingSource
from crawl.sources.ccgp import CcgpSource
from crawl.sources.ggzy import GgzySource
from crawl.sources.jsggzy import JsggzySource
from crawl.sources.jiangsu_zhaobiao import JiangsuZhaobiaoSource
from crawl.sources.qianlima import QianlimaSource
from crawl.sources.rccchina import RccchinaSource
from crawl.sources.tgnet import TgnetSource
from crawl.sources.yfbzb import YfbzbSource

REGISTRY = {
    "cebpub": CebpubSource,
    "chinabidding": ChinabiddingSource,
    "ggzy": GgzySource,
    "ccgp": CcgpSource,
    "jsggzy": JsggzySource,
    "jiangsu_zhaobiao": JiangsuZhaobiaoSource,
    "yfbzb": YfbzbSource,
    "qianlima": QianlimaSource,
    "tgnet": TgnetSource,
    "rccchina": RccchinaSource,
}

# 源站稳定顺序；是否启用由 config/sources.json 的 enabled 控制（与 platforms.json 外壳层九站口径一致）
SOURCE_ORDER = [
    "cebpub", "chinabidding", "ccgp", "ggzy", "jsggzy", "jiangsu_zhaobiao",
    "yfbzb", "qianlima", "tgnet", "rccchina",
]


def enabled_source_ids() -> list[str]:
    """返回已启用源站（按 SOURCE_ORDER）。"""
    from crawl.config_loader import sources_cfg

    cfg = sources_cfg()
    return [sid for sid in SOURCE_ORDER if (cfg.get(sid) or {}).get("enabled") is not False]


def get_source(source_id: str):
    cls = REGISTRY.get(source_id)
    if not cls:
        raise KeyError(f"unknown source: {source_id}")
    return cls()
