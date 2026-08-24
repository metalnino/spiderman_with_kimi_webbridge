"""验证码识别（collector 内核新模块）—— AI 多模态识别优先，确定性识别兜底。

AI 模式（默认 DeepSeek 多模态）：config/ocr_api.json 配置，调用 DeepSeek 视觉模型
  deepseek-v4-flash-vision-exp（OpenAI 兼容 /chat/completions + image_url base64 格式，
  见 https://api-docs.deepseek.com/guides/vision/）；该模型带思考过程，token 预算默认 2000。
  真站验证码为字母数字混合（实测含字母），识别保留 0-9A-Za-z。
确定性模式（兜底）：Pillow 纯算法——灰度→二值→列投影切分→与数字字体模板逐像素比对（仅数字）。

原则：识别是「尽力而为」，错就如实报 验证码错误 并重试（登录侧限次），绝不伪造结果。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG_PATH = ROOT / "config" / "ocr_api.json"

DIGITS = "0123456789"

# DeepSeek 多模态默认配置（OpenAI 兼容）
DEFAULT_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash-vision-exp"


def load_ocr_cfg() -> dict:
    if not CFG_PATH.exists():
        return {"enabled": False}
    try:
        return json.loads(CFG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"enabled": False}


def _preprocess_for_vision(img_bytes: bytes) -> list[bytes]:
    """验证码图多视图预处理：彩色 4x 放大 + 二值化黑字 + 反相二值，全部 PNG 无损。

    小图（60x20 类）直接送视觉模型误读率高；多视图让模型交叉比对。
    PIL 失败时退回原图单视图，不挡识别。
    """
    import io

    from PIL import Image, ImageOps

    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception:
        return [img_bytes]
    views: list[bytes] = []
    try:
        up = ImageOps.autocontrast(img).resize((img.width * 6, img.height * 6), Image.LANCZOS)
        buf = io.BytesIO()
        up.save(buf, format="PNG")
        views.append(buf.getvalue())
        g = img.convert("L")
        bw = ImageOps.autocontrast(g).point(lambda p: 0 if p < 150 else 255)
        buf2 = io.BytesIO()
        bw.resize((bw.width * 6, bw.height * 6), Image.NEAREST).save(buf2, format="PNG")
        views.append(buf2.getvalue())
        inv = bw.point(lambda p: 255 - p)
        buf3 = io.BytesIO()
        inv.resize((inv.width * 6, inv.height * 6), Image.NEAREST).save(buf3, format="PNG")
        views.append(buf3.getvalue())
    except Exception:
        return [img_bytes]
    return views


def ocr_via_api(img_bytes: bytes, cfg: dict) -> str | None:
    """DeepSeek 多模态（或任意 OpenAI 兼容 vision 端点）识别验证码；失败返回 None。"""
    import base64
    import urllib.request

    if not cfg.get("enabled") or not cfg.get("api_key"):
        return None
    endpoint = str(cfg.get("endpoint") or DEFAULT_ENDPOINT).strip()
    if not endpoint:
        return None
    content: list[dict] = []
    for view in _preprocess_for_vision(img_bytes):
        b64 = base64.b64encode(view).decode()
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
    content.append(
        {"type": "text", "text": "这些是同一张网站登录验证码的不同处理视图。请仔细逐字符识别，"
                                "字符可能包含数字和大小写字母，请只输出图中全部字符（保留大小写），不要输出任何解释。"}
    )
    body = json.dumps(
        {
            "model": cfg.get("model") or DEFAULT_MODEL,
            "messages": [{"role": "user", "content": content}],
            # 该模型带思考过程（reasoning_content），token 预算要留够，否则 content 为空
            "max_tokens": int(cfg.get("max_tokens") or 2000),
            "temperature": 0,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        msg = ((data.get("choices") or [{}])[0].get("message") or {})
        text = msg.get("content") or ""
        if not text:
            # 思考型模型可能把答案放在 reasoning_content 里（token 不够时）
            text = msg.get("reasoning_content") or ""
    except Exception:
        return None
    # 验证码可能为字母数字混合（真站实测含字母），保留数字与字母
    code = re.sub(r"[^0-9A-Za-z]", "", text or "")
    return code if code else None


# ---------------------------------------------------------------- 确定性识别 ---

def _to_grayscale_binary(img, threshold: int = 140):
    g = img.convert("L")
    return g.point(lambda p: 255 if p > threshold else 0)


def _split_glyphs(bw) -> list:
    """列投影切分：空白列分界；过宽块按宽高比再切。返回每个字符的二值图。"""
    w, h = bw.size
    cols = []
    for x in range(w):
        dark = sum(1 for y in range(h) if bw.getpixel((x, y)) == 0)
        cols.append(dark > 0)
    # 连续暗列段
    segs = []
    start = None
    for x, dark in enumerate(cols):
        if dark and start is None:
            start = x
        elif not dark and start is not None:
            segs.append((start, x))
            start = None
    if start is not None:
        segs.append((start, w))
    # 合并小间隙（字符间 1~2 列噪声间隙）
    merged = []
    for s, e in segs:
        if merged and s - merged[-1][1] <= 2:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))
    glyphs = []
    for s, e in merged:
        gw = e - s
        if gw < 3:
            continue
        # 过宽 → 从中间再切（粘连字符）
        if gw > h * 0.9:
            mid = s + gw // 2
            glyphs.append(bw.crop((s, 0, mid, h)))
            glyphs.append(bw.crop((mid, 0, e, h)))
        else:
            glyphs.append(bw.crop((s, 0, e, h)))
    return glyphs


def _normalize(img, w: int = 32, h: int = 44):
    """紧凑裁剪 → 保持宽高比缩放进 w×h 画布居中。输入为 L 灰度（暗=前景）。"""
    from PIL import Image

    inv = img.point(lambda p: 255 - p)  # 前景变白，getbbox 取非零区域
    bbox = inv.getbbox()
    if not bbox:
        return Image.new("L", (w, h), 255)
    cell = inv.crop(bbox)
    cw, ch = cell.size
    scale = min((w - 4) / cw, (h - 4) / ch)
    nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
    cell = cell.resize((nw, nh))
    canvas = Image.new("L", (w, h), 255)
    canvas.paste(cell, ((w - nw) // 2, (h - nh) // 2))
    return canvas


def _render_digit_variants(ch: str, font, degraded: bool):
    """渲染单字符变体；degraded=True 时走 JPEG→autocontrast→阈值 劣化管线（与识别端同路径）。"""
    import io

    from PIL import Image, ImageDraw, ImageOps

    img = Image.new("L", (56, 56), 255)
    d = ImageDraw.Draw(img)
    bbox = d.textbbox((0, 0), ch, font=font)
    d.text((28 - (bbox[2] - bbox[0]) / 2 - bbox[0], 28 - (bbox[3] - bbox[1]) / 2 - bbox[1]), ch, fill=0, font=font)
    if not degraded:
        return _normalize(img)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    reloaded = Image.open(io.BytesIO(buf.getvalue())).convert("L")
    reloaded = ImageOps.autocontrast(reloaded)
    bw = _to_grayscale_binary(reloaded, threshold=140)
    return _normalize(bw)


def _make_templates():
    """渲染 0-9 模板（多字号多粗细 × 原图/JPEG劣化 双形态），全部走与识别端相同的 normalize 管线。"""
    from PIL import ImageFont

    fonts = []
    # 小字号覆盖真实验证码字形比例（zhaobiao 验证码 60x20、字形高约 12px）
    for name in ("arial.ttf", "arialbd.ttf", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "cour.ttf"):
        for size in (11, 12, 13, 14, 15, 16, 18, 20, 24, 28, 32):
            try:
                fonts.append(ImageFont.truetype(name, size))
            except OSError:
                continue
    if not fonts:
        fonts = [ImageFont.load_default()]
    templates = {}
    for ch in DIGITS:
        variants = []
        for font in fonts:
            variants.append(_render_digit_variants(ch, font, degraded=False))
            variants.append(_render_digit_variants(ch, font, degraded=True))
        templates[ch] = variants
    return templates


_TEMPLATES = None


def _templates():
    global _TEMPLATES
    if _TEMPLATES is None:
        _TEMPLATES = _make_templates()
    return _TEMPLATES


def _glyph_similarity(glyph, template) -> float:
    """归一化后逐像素相似度（0~1），暗像素错位权重大于背景错位。"""
    g = _normalize(glyph)
    same, total, mismatch_dark = 0, 0, 0
    for y in range(g.height):
        for x in range(g.width):
            total += 1
            gp = g.getpixel((x, y)) < 128
            tp = template.getpixel((x, y)) < 128
            if gp == tp:
                same += 1
            elif gp and not tp:
                mismatch_dark += 1
    return (same - 0.5 * mismatch_dark) / total


def ocr_deterministic(img_bytes: bytes) -> str | None:
    """Pillow 纯算法识别；置信度不足返回 None（调用方如实失败）。"""
    import io

    from PIL import Image, ImageOps

    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception:
        return None
    img = ImageOps.autocontrast(img)
    # 2x 放大再二值化：小图（60x20 类）边缘更稳，笔画比例与模板一致
    img = img.resize((img.width * 2, img.height * 2), Image.BILINEAR)
    bw = _to_grayscale_binary(img, threshold=140)
    glyphs = _split_glyphs(bw)
    if not (3 <= len(glyphs) <= 8):
        return None
    out = []
    for glyph in glyphs:
        best_d, best_sim = None, 0.0
        for ch, variants in _templates().items():
            for t in variants:
                sim = _glyph_similarity(glyph, t)
                if sim > best_sim:
                    best_sim, best_d = sim, ch
        if best_sim < 0.5:
            return None
        out.append(best_d)
    return "".join(out)


def ocr_captcha(img_bytes: bytes) -> str | None:
    """识别验证码（字母数字混合）：AI 多模态优先（双读，一致则用；不一致信首读——靠服务端反馈+重试闭环纠错），失败回退确定性数字识别。"""
    cfg = load_ocr_cfg()
    if cfg.get("enabled"):
        c1 = ocr_via_api(img_bytes, cfg)
        if c1:
            c2 = ocr_via_api(img_bytes, cfg)
            if c2 and c1.lower() != c2.lower():
                return c1  # 不一致不阻塞：信首读，登录侧换图重试有闭环
            return c1
        return None
    return ocr_deterministic(img_bytes)
