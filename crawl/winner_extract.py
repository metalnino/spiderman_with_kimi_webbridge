"""中标企业（供给侧实体）确定性抽取。纯函数，无网络/DB。

只对 result 阶段公告抽取「中标/成交供应商」；抽不到如实返回 None（绝不编造）。
数据来源优先级：summary（详情回填，含正文前 2000 字）> tenderfile_text > title。

红线：本模块只「抽取事实」，不判断「该不该投 / 该不该找它分包」。
"""
from __future__ import annotations

import re

# 中标/成交结果标签（长标签优先，避免「中标供应商名称」被「中标供应商」截断）
_WINNER_LABELS = (
    "中标供应商名称",
    "中标（成交）供应商",
    "中标(成交)供应商",
    "中标供应商",
    "成交供应商名称",
    "成交供应商",
    "中标人名称",
    "中标人",
    "中标单位名称",
    "中标单位",
    "中标企业名称",
    "中标企业",
    "成交单位",
    "供应商名称",
    "成交人",
    "中标商",
)

_LABEL_RE = re.compile(
    r"(?:" + "|".join(re.escape(x) for x in _WINNER_LABELS) + r")"
    r"\s*[:：]\s*(?P<name>[^\n|;；，,。、]{2,80})"
)

# 负向：这些「名字」表示没有中标者 / 流标 / 废标
_NEGATIVES = ("无", "流标", "废标", "终止", "取消", "null", "none", "暂无", "未中标", "—", "-")

# 实体后缀（判断像不像一家单位/供应商）
_ENTITY_SUFFIXES = (
    "有限公司", "股份有限公司", "集团有限公司", "有限责任公司", "集团", "公司",
    "事务所", "设计院", "研究院", "学院", "大学", "医院", "银行", "支行", "分行",
    "中心", "委员会", "管理局", "管理处", "博物馆", "科技馆", "商管", "物业",
    "合作社", "经营部", "商行", "服务部", "工程队", "园林", "绿化",
)

# 名字后常见的噪声标签（截断点，长标签优先；无需前置空格，如「某公司中标金额：X」）
_NOISE_LABEL_RE = re.compile(
    "|".join(
        re.escape(x) for x in (
            "供应商地址", "联系方式", "联系电话", "中标金额", "成交金额", "中标价", "成交价",
            "联系人", "地址", "电话", "邮编", "评标", "得分", "排名", "排序", "金额",
        )
    )
)

# 非实体的噪声短语（抽取结果整体命中则判否）
_NOISE_PHRASES = ("详见", "见附件", "以公告", "以文件", "内容详见", "详情见", "本公告", "本公示")


def _clean_name(raw: str) -> str:
    """清洗抽取到的名字：去括号注释、在噪声标签处截断、去首尾噪声。"""
    name = (raw or "").strip()
    # 去括号内注释（地址/评分/电话等），先于噪声标签截断
    name = re.sub(r"[（(][^）)]*[）)]", " ", name)
    # 在常见后续噪声标签处截断（有无空格均可）
    name = _NOISE_LABEL_RE.split(name)[0]
    name = re.sub(r"\s+", " ", name)
    return name.strip(" ,，。、:：;；|")


def is_plausible_entity(name: str | None) -> bool:
    """判断抽到的名字是否像一家单位/供应商。"""
    if not name:
        return False
    s = (name or "").strip()
    if not s or s.lower() in _NEGATIVES:
        return False
    if any(neg in s for neg in ("流标", "废标", "终止", "未中标")):
        return False
    if any(p in s for p in _NOISE_PHRASES):
        return False
    if len(s) < 4 or len(s) > 80:
        return False
    if any(suf in s for suf in _ENTITY_SUFFIXES):
        return True
    digits = sum(c.isdigit() for c in s)
    if digits > len(s) * 0.5:
        return False
    return len(s) >= 4


def extract_winner_from_text(text: str | None) -> str | None:
    """从一段文本抽中标供应商名；抽不到返回 None。"""
    if not text:
        return None
    m = _LABEL_RE.search(text)
    if not m:
        return None
    name = _clean_name(m.group("name"))
    return name if is_plausible_entity(name) else None


def extract_winner_from_notice(notice: dict) -> dict:
    """notice dict → {winner, source, status}。

    status:
      not_result —— 非结果阶段（不作为中标企业抽取对象）
      extracted  —— 成功抽到
      unknown    —— 结果阶段但抽不到（无 summary / 登录墙 / 真流标），如实 unknown
    """
    n = notice or {}
    stage = (n.get("notice_stage") or "").strip()
    if stage != "result":
        return {"winner": None, "source": None, "status": "not_result"}
    for src, txt in (
        ("summary", n.get("summary")),
        ("tenderfile_text", n.get("tenderfile_text")),
        ("title", n.get("title")),
    ):
        w = extract_winner_from_text(txt)
        if w:
            return {"winner": w, "source": src, "status": "extracted"}
    return {"winner": None, "source": None, "status": "unknown"}
