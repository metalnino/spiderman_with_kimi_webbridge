from crawl.sources.cebpub import CebpubSource
from crawl.sources.chinabidding import ChinabiddingSource
from crawl.sources.ccgp import CcgpSource
from crawl.sources.ggzy import GgzySource

REGISTRY = {
    "cebpub": CebpubSource,
    "chinabidding": ChinabiddingSource,
    "ggzy": GgzySource,
    "ccgp": CcgpSource,
}


def get_source(source_id: str):
    cls = REGISTRY.get(source_id)
    if not cls:
        raise KeyError(f"unknown source: {source_id}")
    return cls()
