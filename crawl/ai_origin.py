"""AI 源头发现通道 —— 让模型直接参与「找源头」，而不只是抽锚点。

为什么需要它（前两轮实测暴露的能力边界）：
  规则路径依赖两件事：① 搜索引擎收录了源头页；② 我的 URL/标题启发式能从候选里挑对。
  两者都会失效：
    - 招必得这类第三方交易平台**不被搜索引擎收录** → 检索结果里根本没有它；
    - 企业官网/政府站的候选里混着镜像详情页（`diuta.com`）、相邻公告（`page_id/36965`），
      纯字符相似度分不出「哪条域名是采购人自己的」。

AI 恰好补这两个洞：它有**世界知识**（"安徽交控的官网是 ahjg.com"、"央企一般在集团电商平台发布"），
也能**读懂 URL + 标题的语义**（"这条挂在 cebpubservice 上的是转载，那条在 wzbank.cn 上的才是官网"）。

红线（和 ai_extract 一致，且更严）：
  - AI **只提候选**（域名 / 从已有结果里选一条），**不做认定**；
  - 认定一律由页面证据（标题/核心名/编号 + 日期）在 `origin_trace` 里确定性完成；
  - AI 编的域名/URL 全部要经过「能不能打开、页面里有没有这条公告」的实测，编造即被拦下；
  - 任何失败（无 key/超时/坏 JSON）返回空，规则路径不受影响。
"""
from __future__ import annotations

SUGGEST_FIELDS = ("name", "domain", "level", "confidence", "reason")
LEVELS = ("head", "gov", "platform")

_SUGGEST_PROMPT = """你是中国招投标领域的资料员。给定一条招标公告的采购人与项目信息，
请判断「这条公告最早发布在哪个平台/网站」。

只输出一个 JSON 对象，不要解释：
{
  "officialSite": "采购人自己的官网域名，如 wzbank.cn；不确定填 null",
  "portals": [
    {"name": "平台名称", "domain": "域名（不带 http:// 与路径）",
     "level": "head|gov|platform", "confidence": 0.0~1.0,
     "reason": "一句话依据"}
  ],
  "searchHint": "还可以试的检索词，或 null"
}

硬性要求：
1. domain 必须是你**确有把握的真实域名**；没把握就**不要写**，宁可返回空数组。编造域名是最严重的错误。
2. level 取值：head=采购人自建（集团电商平台/银行医院高校官网采购栏目）；
   gov=政府公共资源交易/政府采购平台；platform=第三方电子交易平台（如招必得、各地交易中心）。
3. 按可能性排序，最多 4 条。
4. 央企/国企优先考虑其集团自有电商平台；银行/医院/高校优先考虑其官网的采购/招标栏目；
   地方国企优先考虑属地公共资源交易中心。

采购人：{buyer}
项目：{title}
地区：{city}
正文已知线索：{hints}
"""

_PICK_PROMPT = """你是中国招投标领域的资料员。下面是搜索引擎返回的若干条结果（标题 + URL），
请判断：**哪一条最可能是这条招标公告的「原始发布页」**（即采购人自己发布的那个页面）。

判断依据（按重要性）：
1. 域名是不是**采购人自己的**（如温州银行 → wzbank.cn / wzcb.com.cn；安徽交控 → ahjg.com）；
2. URL 形态是不是**公告详情页**（带 id/page_id/display.php 等），而不是栏目列表页；
3. 标题是否就是这条公告（注意排除同一项目的「中标结果/候选人公示」等别的阶段）。

排除项：聚合/镜像站（qianlima、chinabidding、yfbzb、bidcenter、okcis、采招网、招标网、剑鱼、
企查查/天眼查等企业信息站）、栏目列表页、以及其他项目的公告。

只输出一个 JSON 对象，不要解释：
{"url": "选中的 URL，或 null", "confidence": 0.0~1.0, "reason": "一句话依据"}

目标公告标题：{title}
采购人：{buyer}

候选列表：
{candidates}
"""


def _chat_json(prompt: str, *, timeout: int = 30, max_tokens: int = 900) -> dict:
    """一次 DeepSeek 调用 → JSON 对象；禁用/失败/坏输出一律返回 {}。"""
    try:
        from crawl.ai_extract import _chat, _parse_json, load_cfg

        cfg = load_cfg()
        if not cfg.get("enabled"):
            return {}
        cfg = dict(cfg)
        cfg["timeout_sec"] = timeout
        cfg["max_tokens"] = max_tokens
        raw = _chat([{"role": "user", "content": prompt}], cfg)
        if not raw:
            return {}
        return _parse_json(raw)
    except Exception:  # noqa: BLE001 —— AI 永不阻塞主链
        return {}


def _clean_domain(v) -> str | None:
    import re

    s = str(v or "").strip().lower()
    if not s or s in ("null", "none", "无", "未知"):
        return None
    s = re.sub(r"^https?://", "", s).split("/")[0].split(":")[0]
    if "." not in s or len(s) < 4 or " " in s:
        return None
    return s


def suggest_portals(buyer: str | None, title: str, *, city: str | None = None,
                    hints: dict | None = None) -> dict:
    """AI 推测源头平台/官网。返回 {"officialSite","portals":[{name,domain,level,confidence,reason}]}。

    纯建议：**返回值不构成认定**，调用方必须逐个实测（能否打开 + 页面里有没有这条公告）。
    """
    if not (buyer or title):
        return {"officialSite": None, "portals": []}
    h = hints or {}
    hint_txt = "；".join(x for x in (
        f"采购人={buyer}" if buyer else "",
        f"项目编号={h.get('projectCode')}" if h.get("projectCode") else "",
        f"邮箱域名={','.join(h.get('emailDomains') or [])}" if h.get("emailDomains") else "",
        f"正文URL={','.join((h.get('urls') or [])[:3])}" if h.get("urls") else "",
        f"发布媒介={h.get('mediaLine')}" if h.get("mediaLine") else "",
    ) if x) or "（无）"
    prompt = (_SUGGEST_PROMPT
              .replace("{buyer}", str(buyer or "未知"))
              .replace("{title}", str(title or ""))
              .replace("{city}", str(city or "未知"))
              .replace("{hints}", hint_txt[:600]))
    obj = _chat_json(prompt, max_tokens=900)
    official = _clean_domain(obj.get("officialSite"))
    out: list[dict] = []
    for p in (obj.get("portals") or [])[:6]:
        if not isinstance(p, dict):
            continue
        d = _clean_domain(p.get("domain"))
        if not d:
            continue
        lv = str(p.get("level") or "").strip().lower()
        if lv not in LEVELS:
            lv = "platform"
        try:
            conf = float(p.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        out.append({"name": str(p.get("name") or d)[:60], "domain": d, "level": lv,
                    "confidence": round(max(0.0, min(1.0, conf)), 2),
                    "reason": str(p.get("reason") or "")[:120], "source": "ai"})
    if official and all(o["domain"] != official for o in out):
        out.insert(0, {"name": f"{buyer or ''}官网".strip(), "domain": official, "level": "head",
                       "confidence": 0.6, "reason": "AI 推测的主体官网", "source": "ai"})
    return {"officialSite": official, "portals": out, "searchHint": obj.get("searchHint")}


def pick_origin(title: str, candidates: list[dict], *, buyer: str | None = None) -> dict:
    """从**已检索到的真实结果**里让 AI 选出源头页。返回 {"url","confidence","reason"}。

    这是最安全的 AI 用法：AI 只在真实、可抓取的 URL 里做选择（不能凭空造地址），
    并且选出来的 URL 仍要过 `_fetch_and_verify` 的页面证据校验。
    """
    if not candidates:
        return {}
    lines = []
    for i, c in enumerate(candidates[:24], 1):
        lines.append(f"{i}. {str(c.get('title') or '')[:90]} | {c.get('url')}")
    prompt = (_PICK_PROMPT
              .replace("{title}", str(title or ""))
              .replace("{buyer}", str(buyer or "未知"))
              .replace("{candidates}", "\n".join(lines)))
    obj = _chat_json(prompt, max_tokens=300)
    url = str(obj.get("url") or "").strip()
    if not url.startswith("http"):
        return {}
    known = {str(c.get("url") or "") for c in candidates}
    if url not in known:
        # 只接受候选里真实存在的 URL（防止模型改写/拼接地址）
        for k in known:
            if k and (url in k or k in url):
                url = k
                break
        else:
            return {}
    try:
        conf = float(obj.get("confidence") or 0)
    except (TypeError, ValueError):
        conf = 0.0
    return {"url": url, "confidence": round(max(0.0, min(1.0, conf)), 2),
            "reason": str(obj.get("reason") or "")[:160]}
