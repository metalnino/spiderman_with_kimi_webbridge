"""源头线索抽取（源头追溯员第一层）—— 从「转载正文」里挖出找源头要用的锚点。

第一性原理：聚合站正文本身几乎必然留着原文的**身份信息**（谁发的、发在哪、文号是多少）。
这些锚点才是找源头的钥匙，而不是标题：
  - 采购人/招标人   → 主体名称 → 主体自己的电子采购平台（最高价值：一手正文+可下采购文件）
  - 电子邮箱后缀     → 企业域名（@huanengleasing.com → huanengleasing.com → 华能系）
  - 正文里的 URL     → 发布媒介/报名系统（往往直接就是源头平台）
  - 项目编号/采购编号 → 在源头平台站内检索的最强关键词（HNFZ2026-09-2-00396）

规则与 AI 分工（红线）：
  - 规则抽「确定的东西」：邮箱、URL、编号、标签行，抽到什么就是什么；
  - AI 只抽「规则抽不到的语义字段」（主体规范全称、主体简称、可能的平台名），抽不到输出 null；
  - 两者**都不判断真假、不猜域名**；域名候选交给下一层去实测（打开页面确认标题/编号一致）。
"""
from __future__ import annotations

import re

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})")
URL_RE = re.compile(r"https?://[^\s\"'<>）)】\]，,；;、]+", re.I)

# 主体标签（长标签优先，避免「采购」把「采购人」吃掉）
BUYER_LABELS = (
    "采购人名称", "招标人名称", "采购单位名称", "招标单位名称",
    "采购人", "招标人", "采购单位", "招标单位", "建设单位", "需求单位",
    "业主单位", "采购机构", "发包人", "比选人", "询价人", "邀请人",
)
AGENCY_LABELS = ("采购代理机构", "招标代理机构", "代理机构", "采购代理", "招标代理")
_AGENT_STOP = re.compile(r"[，,；;。\n\r\t]|（|\(|地址|电话|联系|邮箱|邮编")

# 项目/采购编号：形如 HNFZ2026-09-2-00396 / SCQCTJT2026GKFW071 / ZB2026091801
CODE_RE = re.compile(
    r"(?:采购|招标|项目|公告|交易)?编号\s*[:：]\s*([A-Za-z0-9][A-Za-z0-9\-_/（）()]{5,40})",
)
_CODE_LOOSE_RE = re.compile(r"\b([A-Z]{2,10}\d{6,}[A-Z0-9\-]*)\b")

PORTAL_HINTS = ("电子商务平台", "电子采购平台", "电子招标", "采购交易平台", "招标采购平台",
                "阳光采购平台", "公共资源交易", "招投标公共服务平台", "供应链平台", "采购门户")

# 发布媒介行：明说「在哪里发布」——最直接的源头证据
_MEDIA_RE = re.compile(
    r"(?:发布(?:公告)?的?媒介|公告发布媒介|发布平台|发布网站|发布媒体|本公告在|公告在)"
    r"[^。\n]{0,20}?[:：]?\s*([^。\n]{2,160})",
)


def _clean(s: str | None) -> str | None:
    if not s:
        return None
    s = re.sub(r"\s+", " ", str(s)).strip(" :：,，。.、;；|")
    return s or None


def _cut_label_value(text: str, label: str, *, max_len: int = 60) -> str | None:
    """取「标签 + 分隔符」后的值；到句读/下一个标签为止。"""
    for m in re.finditer(re.escape(label) + r"\s*(?:名称)?\s*[:：]?\s*", text):
        seg = text[m.end():m.end() + max_len * 2]
        val = _AGENT_STOP.split(seg)[0]
        # 常见写法「采购人为：XX」「招标人是 XX」「采购人系 XX」：剥掉系动词与残留冒号
        val = re.sub(r"^\s*(?:为|是|系)\s*[:：]?\s*", "", val)
        val = _clean(val)
        if val and 3 <= len(val) <= max_len:
            return val
    return None


def rule_hints(text: str | None, title: str = "") -> dict:
    """纯规则抽取（确定性，永不抛）。返回字段缺失即 None。"""
    t = str(text or "")
    hay = f"{title}\n{t}"
    emails = []
    for d in EMAIL_RE.findall(t):
        d = d.lower().strip(".")
        if d not in emails and not d.endswith(("qq.com", "163.com", "126.com", "sina.com", "gmail.com", "outlook.com", "hotmail.com")):
            emails.append(d)
    urls: list[str] = []
    for u in URL_RE.findall(t):
        u = u.rstrip(".,;:)）】]")
        if u not in urls:
            urls.append(u)
    buyer = None
    for lb in BUYER_LABELS:
        buyer = _cut_label_value(t, lb)
        if buyer:
            break
    if not buyer:
        # 标题前缀「XX公司关于…」「XX有限公司YY项目」兜底
        m = re.match(r"([\u4e00-\u9fa5A-Za-z0-9（）()]{4,40}?(?:公司|集团|中心|医院|学校|机场|银行|大学|研究所|研究院|管理局|委员会))", title or "")
        buyer = _clean(m.group(1)) if m else None
    agency = None
    for lb in AGENCY_LABELS:
        agency = _cut_label_value(t, lb)
        if agency:
            break
    code = None
    m = CODE_RE.search(hay)
    if m:
        code = _clean(m.group(1))
    if not code:
        m = _CODE_LOOSE_RE.search(hay)
        code = _clean(m.group(1)) if m else None
    media = None
    m = _MEDIA_RE.search(t)
    if m:
        media = _clean(URL_RE.sub(" ", m.group(1)))[:120] if m.group(1) else None
    portal_words = [w for w in PORTAL_HINTS if w in t]
    return {
        "buyer": buyer,
        "agency": agency,
        "projectCode": code,
        "emailDomains": emails,
        "urls": urls[:20],
        "mediaLine": media,
        "portalWords": portal_words[:6],
    }


_AI_FIELDS = ("buyer", "buyerShort", "portalName", "portalDomainGuess")

_AI_PROMPT = (
    "你是招标公告的「源头线索抽取器」。只做抽取，不做判断，不编造。\n"
    "从下面这段**转载公告正文**里抽取找「原始发布源头」需要的线索，只输出一个 JSON 对象：\n"
    "- buyer: 采购人/招标人的规范全称（原文照抄，不要改写）\n"
    "- buyerShort: 该主体最常用的简称/集团名（如「华能天成融资租赁有限公司」→「华能」；抽不到 null）\n"
    "- portalName: 正文里提到的发布/报名/下载采购文件的平台名称（如「中国华能集团电子商务平台」；没提到就 null）\n"
    "- portalDomainGuess: 正文里**原样出现**的平台域名（不得凭印象编造；没有就 null）\n"
    "抽不到一律 null。不要输出解释文字。\n\n公告正文：\n{text}"
)


def ai_hints(text: str | None) -> dict:
    """AI 语义抽取（复用 DeepSeek 配置）；禁用/失败/坏输出一律返回 {}。"""
    if not text or len(str(text)) < 40:
        return {}
    try:
        from crawl.ai_extract import _chat, _parse_json, load_cfg

        cfg = load_cfg()
        if not cfg.get("enabled"):
            return {}
        raw = _chat([{"role": "user", "content": _AI_PROMPT.replace("{text}", str(text)[:5000])}], cfg)
        if not raw:
            return {}
        obj = _parse_json(raw)
    except Exception:  # noqa: BLE001 —— AI 永远不阻塞主链
        return {}
    out: dict = {}
    for k in _AI_FIELDS:
        v = obj.get(k)
        if isinstance(v, str) and v.strip() and v.strip().lower() not in ("null", "none", "无", "未知", "n/a"):
            out[k] = v.strip()
    return out


def merge(rule: dict, ai: dict) -> dict:
    """规则优先（确定性 > 概率性），AI 只补规则空位。"""
    out = dict(rule or {})
    for k in ("buyer", "portalName"):
        if not out.get(k) and (ai or {}).get(k):
            out[k] = ai[k]
    out["buyerShort"] = (ai or {}).get("buyerShort")
    out["portalDomainGuess"] = (ai or {}).get("portalDomainGuess")
    out["aiUsed"] = bool(ai)
    return out


def fill_missing(base: dict, extra: dict) -> dict:
    """用兄弟公告的锚点补 base 的空位（只补空，不覆盖已有值）。"""
    out = dict(base or {})
    for k in ("buyer", "agency", "projectCode", "mediaLine", "buyerShort", "portalDomainGuess"):
        if not out.get(k) and (extra or {}).get(k):
            out[k] = extra[k]
    for k in ("emailDomains", "urls", "portalWords"):
        cur = list(out.get(k) or [])
        for v in (extra or {}).get(k) or []:
            if v not in cur:
                cur.append(v)
        out[k] = cur
    out["aiUsed"] = bool(out.get("aiUsed")) or bool((extra or {}).get("aiUsed"))
    return out


def extract(text: str | None, title: str = "", *, use_ai: bool = True) -> dict:
    """规则 + AI 合并抽取。返回的字段全部可能为 None，调用方需自行判空。"""
    rule = rule_hints(text, title)
    ai = ai_hints(text) if use_ai else {}
    return merge(rule, ai)


def search_queries(hints: dict, title: str = "", *, max_queries: int = 4) -> list[str]:
    """线索 → 外部检索词（按「能唯一定位到源头」的强度排序）。

    四类（实测有效）：
      ① 项目编号（唯一，直接命中源头详情页）；
      ② 项目核心名（多数站按标题收录转载页，能带出一手平台）；
      ③ 核心名 + 原始公告（把「交易公告/原始发布」类页面顶上来）；
      ④ **平台发现型**：主体 + 「招标采购交易平台」——这一条是用来找「主体自己在哪个平台发」的，
         实测能把 gov 交易平台/一手门户顶出来（如 ggzy.hzctc.hangzhou.gov.cn），
         而纯标题检索只会一直返回镜像站。
    """
    from crawl.stage import project_core

    core = project_core(title or "")[:40]
    buyer = (hints or {}).get("buyer") or (hints or {}).get("buyerShort")
    code = (hints or {}).get("projectCode")
    qs: list[str] = []
    if code and len(str(code)) >= 8:
        qs.append(f'"{code}"')
    if core:
        # 核心名常自带主体前缀（project_core 保留公司名），再加主体就成了重复词，反而降权
        if buyer and not core.startswith(str(buyer)[:6]):
            qs.append(f"{buyer} {core}")
        qs.append(core)
    if buyer:
        # 平台发现型（排在「原始公告」之前：它才是找一手平台的那一条）
        qs.append(f"{buyer} 招标采购交易平台")
    elif core:
        qs.append(f"{core} 交易平台")
    if core:
        qs.append(f"{core} 原始公告")
    seen: list[str] = []
    for q in qs:
        q = re.sub(r"\s+", " ", q).strip()
        if q and q not in seen:
            seen.append(q)
    return seen[:max_queries]


def domain_of(url: str) -> str:
    return re.sub(r"^https?://", "", (url or "")).split("/")[0].split(":")[0].lower()
