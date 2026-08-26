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


def _platform_enabled_ids() -> list[str] | None:
    """config/platforms.json（员工外壳改进层）里启用的平台 id；文件缺失/解析失败返回 None。

    platforms.json 是本机启用口径的唯一权威（Windows 任务 SpidermanCollector 读它）；
    返回 None 表示「无外壳层」，调用方回退 config/sources.json（Docker/NAS 场景）。
    """
    from crawl.config_loader import ROOT, load_json

    if not (ROOT / "config" / "platforms.json").exists():
        return None
    try:
        entries = load_json("config/platforms.json")
    except (OSError, ValueError):
        return None
    ids: list[str] = []
    for e in entries or []:
        if isinstance(e, dict) and e.get("id") and e.get("enabled") is not False:
            ids.append(str(e["id"]))
    return ids


def enabled_source_ids() -> list[str]:
    """返回已启用源站（按 SOURCE_ORDER）。

    唯一权威 = config/platforms.json；外壳层缺失时才回退 config/sources.json。
    """
    plat = _platform_enabled_ids()
    if plat is not None:
        return [sid for sid in SOURCE_ORDER if sid in plat]
    from crawl.config_loader import sources_cfg

    cfg = sources_cfg()
    return [sid for sid in SOURCE_ORDER if (cfg.get(sid) or {}).get("enabled") is not False]


def source_config_drift() -> dict:
    """platforms.json 与 sources.json 启用集对比，供启动告警 / health / 回归测试。

    drifted=True 说明两层口径不一致（改了其中一层忘同步另一层）。
    """
    plat = _platform_enabled_ids()
    from crawl.config_loader import sources_cfg

    cfg = sources_cfg()
    kern = [sid for sid in SOURCE_ORDER if (cfg.get(sid) or {}).get("enabled") is not False]
    if plat is None:
        return {"has_platforms": False, "kernel_enabled": kern, "drifted": False}
    ps, ks = sorted(plat), sorted(kern)
    return {
        "has_platforms": True,
        "platforms_enabled": ps,
        "kernel_enabled": ks,
        "drifted": ps != ks,
        "only_platforms": sorted(set(ps) - set(ks)),
        "only_kernel": sorted(set(ks) - set(ps)),
    }


def get_source(source_id: str):
    cls = REGISTRY.get(source_id)
    if not cls:
        raise KeyError(f"unknown source: {source_id}")
    return cls()
