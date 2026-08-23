"""公告阶段识别与项目时间线键（P4）。

阶段口径（rank 即时间线顺序）：
  intent 意向/预告 → bidding 招标公告 → change 更正澄清 → preselect 资格预审
  → opening 开标评标 → candidate 中标候选人公示 → result 中标/成交结果 → terminated 终止/流标
  → other 其他

识别依据：标题关键词（优先，跨站一致）→ 源站 notice_type 编码映射 → other。
project_key：标题去掉阶段词/日期/标点/噪声块后的核心名 + 城市，做 sha1；
  用于把同一项目不同阶段的公告串成时间线（同站/跨站通用）。
  「二次采购」等批次词保留在核心里，不与首次采购合并。
"""
from __future__ import annotations

import hashlib
import re

# (stage_key, rank, 展示名, 标题关键词) —— 匹配顺序即优先级（候选人先于结果，开标失败先于开标）
STAGES: list[tuple[str, int, str, list[str]]] = [
    ("intent", 1, "意向预告", ["采购意向", "采购需求公示", "招标计划", "采购预告"]),
    ("bidding", 2, "招标公告", [
        "招标公告", "采购公告", "询比", "询价书", "询价公告", "竞争性磋商", "竞争性谈判",
        "单一来源", "比选公告", "谈判采购", "邀请函", "邀请公告", "交易公告", "竞价公告",
        "公开招标", "征集公告",
    ]),
    ("change", 3, "更正澄清", ["更正公告", "澄清公告", "延期公告", "变更公告", "补充公告", "答疑"]),
    ("preselect", 4, "资格预审", ["资格预审", "资格审查", "入围名单"]),
    ("opening", 5, "开标评标", ["开标记录", "开标结果", "评标结果", "评标报告"]),
    ("candidate", 6, "候选人公示", ["候选人公示", "中标候选人", "成交候选人", "预中标", "预成交"]),
    ("result", 7, "结果公告", [
        "中标结果", "中标公告", "结果公告", "结果公示", "成交公告", "成交公示",
        "采购结果", "中标（成交）", "中标(成交)",
    ]),
    ("terminated", 8, "终止流标", [
        "终止公告", "流标", "废标", "暂停公告", "开标失败", "取消公告", "采购失败",
    ]),
    ("other", 9, "其他", []),
]

STAGE_LABELS = {k: label for k, _, label, _ in STAGES}
STAGE_RANKS = {k: rank for k, rank, _, _ in STAGES}

# 源站 notice_type 编码 → 阶段（标题未命中关键词时的兜底）
NT_MAP = {
    "ZBGG": "bidding",   # 采招网：招标公告
    "ZBGS": "result",    # 采招网：中标公示
    "bidding": "bidding",
    "succeed": "result",
    "change": "change",
    "free": "other",
    "other": "other",
    "成交公示": "result",
    "中标公示": "result",
    "招标公告": "bidding",
}

# 阶段词（project_key 剔除用）：所有 STAGES 关键词 + 通用公告词
_STAGE_WORDS = sorted(
    {w for _, _, _, ws in STAGES for w in ws}
    | {"公告", "公示", "候选人", "成交", "中标", "结果", "更正", "延期", "澄清",
       "终止", "变更", "补充", "答疑", "招标", "采购", "邀请", "询价", "谈判",
       "比选", "开标", "失败", "资格预审", "资格审查", "入围", "评标", "预中标",
       "预成交", "公开", "交易", "竞价", "竞争性", "单一来源", "流标", "废标",
       "暂停", "取消"},
    key=len,
    reverse=True,  # 长词优先，避免「成交候选人」被「成交」拆散
)

_WORD_RE = re.compile("|".join(re.escape(w) for w in _STAGE_WORDS))
# 噪声块：查询ID、抓取标注、代发、批次后缀（批次保留在核心，仅去掉括号编号）
_NOISE_RE = re.compile(
    r"\(查询ID:[^)]*\)"                      # 江苏站抓取标注
    r"|\([^)]*相关在信息中\)"                 # 关键词命中标注
    r"|（代发）|\(代发\)"
    r"|\([一二三四五六七八九十]+\)\s*$"       # 中标公告(二) 之类
)
# 日期与年度：去掉后核心名更稳
_DATE_RE = re.compile(r"20\d{2}[-/年.]\d{0,2}[-/月.]?\d{0,2}日?|20\d{2}年度?|年度?")
_PUNCT_RE = re.compile(r"[\s（）()【】\[\]{}：:，,。.、/\\\-—–_+|·《》\"'“”]+")


def classify_stage(title: str, notice_type: str | None = None) -> tuple[str, int]:
    """返回 (stage_key, rank)。标题关键词优先，其次 notice_type 映射，兜底 other。"""
    t = title or ""
    for key, rank, _label, words in STAGES:
        for w in words:
            if w and w in t:
                return key, rank
    if notice_type:
        mapped = NT_MAP.get(notice_type)
        if mapped:
            return mapped, STAGE_RANKS[mapped]
    return "other", STAGE_RANKS["other"]


def project_core(title: str) -> str:
    """标题 → 核心名（去阶段词/日期/噪声/标点；批次词如「二次」保留）。"""
    t = title or ""
    for _ in range(3):  # 噪声块可能嵌套（如「中标公告(二)(绿植租摆 相关在信息中)」），多遍剥到稳定
        t = _NOISE_RE.sub(" ", t)
    t = _WORD_RE.sub(" ", t)
    t = _DATE_RE.sub(" ", t)
    t = _PUNCT_RE.sub("", t)
    return t.strip()


def project_key(title: str, city: str | None = None) -> tuple[str, str]:
    """返回 (sha1_hex, core_text)。城市参与键，避免异地同名项目误串。"""
    core = project_core(title)
    key_src = f"{city or ''}|{core}".strip("|")
    return hashlib.sha1(key_src.encode("utf-8")).hexdigest(), core
