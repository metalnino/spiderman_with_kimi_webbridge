"""AI 详情字段抽取（DeepSeek 文本模型，OpenAI 兼容 /chat/completions）。

用途：确定性规则抓不到关键字段（采购人/代理/金额/截止/中标人）时，把详情正文
（summary）交给 LLM 做结构化抽取。这是采集员从「纯规则」走向「agent」的那一步。

红线（不越界）：
- AI 只做「抽取」，不做「判断」（不判断投不投、不判断资质合不合格）；
- 抽不到的字段输出 null，绝不编造；
- 任何失败（无 key / 网络 / 超时 / 模型不存在 / JSON 坏）一律降级返回 {}，规则路径不受影响。

api_key 复用 config/ocr_api.json（数字员工 DeepSeek key），endpoint 同源。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG_PATH = ROOT / "config" / "ai_extract.json"
OCR_CFG_PATH = ROOT / "config" / "ocr_api.json"

DEFAULT_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"

# 允许抽取的字段（与 config 保持同步；sanitize 只保留这些）
KNOWN_FIELDS = ("buyer", "agency", "amount_text", "deadline", "winner")


def load_cfg() -> dict:
    """合并 ai_extract.json（模型/字段）+ ocr_api.json（endpoint/api_key）。失败返回 disabled。"""
    cfg: dict = {"enabled": False}
    if CFG_PATH.exists():
        try:
            cfg.update(json.loads(CFG_PATH.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            return {"enabled": False}
    # api_key / endpoint 复用 ocr_api.json（同 key，不重复存）
    key, endpoint = "", ""
    if OCR_CFG_PATH.exists():
        try:
            ocr = json.loads(OCR_CFG_PATH.read_text(encoding="utf-8"))
            key = str(ocr.get("api_key") or "").strip()
            endpoint = str(ocr.get("endpoint") or "").strip()
        except (OSError, json.JSONDecodeError):
            pass
    if not cfg.get("endpoint"):
        cfg["endpoint"] = endpoint or DEFAULT_ENDPOINT
    cfg["api_key"] = key
    if not cfg.get("enabled") or not key:
        cfg["enabled"] = False
    return cfg


def _chat(messages: list[dict], cfg: dict) -> str | None:
    """OpenAI 兼容 chat 调用；任何异常返回 None（降级）。"""
    import urllib.request

    body = json.dumps(
        {
            "model": cfg.get("model") or DEFAULT_MODEL,
            "messages": messages,
            "max_tokens": int(cfg.get("max_tokens") or 800),
            "temperature": 0,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        str(cfg.get("endpoint") or DEFAULT_ENDPOINT),
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=int(cfg.get("timeout_sec") or 25)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        msg = ((data.get("choices") or [{}])[0].get("message") or {})
        text = msg.get("content") or ""
        if not text:
            text = msg.get("reasoning_content") or ""
    except Exception:
        return None
    return text


def _parse_json(text: str) -> dict:
    """从模型输出里抠 JSON 对象（容忍 ```json 围栏/前后噪声）。失败返回 {}。"""
    if not text:
        return {}
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return {}
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


def _sanitize(obj: dict, fields) -> dict:
    """只保留已知字段；值必须是非空字符串，否则 None（诚实空）。"""
    out: dict = {}
    for k in fields or KNOWN_FIELDS:
        v = obj.get(k)
        if isinstance(v, str) and v.strip() and v.strip().lower() not in ("null", "none", "无", "不详", "n/a"):
            out[k] = v.strip()
        else:
            out[k] = None
    return out


def extract_fields(text: str | None, fields=None) -> dict:
    """主入口：text（详情正文/summary）→ 结构化字段 dict。失败/禁用 → {}。"""
    if not text or not str(text).strip():
        return {}
    cfg = load_cfg()
    if not cfg.get("enabled"):
        return {}
    want = [f for f in (fields or KNOWN_FIELDS) if f in KNOWN_FIELDS]
    if not want:
        return {}
    field_desc = {
        "buyer": "采购人/招标人名称",
        "agency": "代理机构名称",
        "amount_text": "预算金额或中标/成交金额原文（含单位，如 12.5万元）",
        "deadline": "投标截止时间或开标时间（原文，可含日期）",
        "winner": "中标/成交供应商名称",
    }
    lines = "\n".join(f"- {k}: {field_desc[k]}" for k in want)
    prompt = (
        "你是招标公告信息抽取器。请从下面的公告详情文本中抽取字段，只输出一个 JSON 对象，"
        "不要输出任何解释或多余文字。抽不到的字段输出 null。\n"
        f"字段定义：\n{lines}\n\n公告详情文本：\n{str(text)[:6000]}"
    )
    raw = _chat([{"role": "user", "content": prompt}], cfg)
    if raw is None:
        return {}  # 网络/超时/模型失败 → 空，走规则
    result = _sanitize(_parse_json(raw), want)
    # 全空视为「无结果」（抽不到/坏输出），返回 {}，避免全 None 伪结果
    if not any(v for v in result.values()):
        return {}
    return result
