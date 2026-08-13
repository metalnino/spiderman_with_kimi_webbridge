from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote, urlencode

import requests

ROOT = Path(__file__).resolve().parents[1]
sys_path_note = ""
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def decode(raw: bytes) -> str:
    for enc in ("utf-8", "gbk", "gb2312"):
        try:
            t = raw.decode(enc)
            if "�" not in t[:200] or enc == "gbk":
                return t
        except Exception:
            continue
    return raw.decode("utf-8", "ignore")


def extract(html: str) -> list[dict]:
    items = []
    # detail links often contain /zb/ or numeric ids
    for m in re.finditer(
        r'<a[^>]+href="([^"]+)"[^>]*(?:title="([^"]*)")?[^>]*>([\s\S]*?)</a>',
        html,
        re.I,
    ):
        href = m.group(1)
        title = m.group(2) or re.sub(r"<[^>]+>", "", m.group(3) or "")
        title = re.sub(r"\s+", " ", title).strip()
        if len(title) < 12:
            continue
        if not re.search(r"(/psearch/|/zb/|info|detail|\d{6,})", href, re.I):
            # keep long titles on same domain
            if "zhaobiao.cn" not in href and not href.startswith("/"):
                continue
        if any(bad in href for bad in ["login", "register", "ssearch_q_", "javascript", "help"]):
            continue
        date = None
        # nearby date in following 200 chars
        pos = m.end()
        tail = html[pos : pos + 220]
        dm = re.search(r"(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})", tail)
        if dm:
            date = dm.group(1).replace("/", "-").replace(".", "-")
        items.append({"title": title[:200], "href": href[:300], "date": date})
    # dedupe by href
    seen = set()
    out = []
    for it in items:
        if it["href"] in seen:
            continue
        seen.add(it["href"])
        out.append(it)
    return out


def main() -> None:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"})
    s.get("https://jiangsu.zhaobiao.cn/", timeout=30)
    kw = "绿化养护"
    q = urlencode(
        {
            "page": "1",
            "attachment": "1",
            "channels": "",
            "area": "",
            "field": "all",
            "queryword": kw,
        },
        encoding="utf-8",
    )
    urls = [
        f"https://jiangsu.zhaobiao.cn/psearch/Dqsearch?{q}",
        f"https://jiangsu.zhaobiao.cn/psearch/Dqsearch?page=1&queryword={quote(kw)}&area=320000",
        f"https://jiangsu.zhaobiao.cn/psearch/Dqsearch?page=1&queryword={quote(kw)}&area=江苏",
    ]
    report = {}
    for u in urls:
        r = s.get(u, timeout=30, headers={"Referer": "https://jiangsu.zhaobiao.cn/"})
        text = decode(r.content)
        (ROOT / "data" / "web" / "zhaobiao_psearch_sample.html").write_bytes(r.content)
        items = extract(text)
        report[u] = {
            "status": r.status_code,
            "final": str(r.url),
            "len": len(text),
            "locked": bool(re.search(r"请登录|登录后|开通会员", text[:15000])),
            "items_n": len(items),
            "items": items[:15],
            "has_kw": kw in text,
        }
    path = ROOT / "data" / "web" / "jiangsu_zhaobiao_probe7.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2)[:8000])
    print("WROTE", path)


if __name__ == "__main__":
    main()
