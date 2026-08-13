from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def main() -> None:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    s.get("https://jiangsu.zhaobiao.cn/", timeout=30)
    kw = "绿化养护"
    u = f"https://jiangsu.zhaobiao.cn/ssearch_q_{quote(kw)}_qs_h_s_01_pro_320000_f_03_p_1.html"
    r = s.get(u, timeout=30, headers={"Referer": "https://jiangsu.zhaobiao.cn/"})
    raw = r.content
    (ROOT / "data" / "web" / "zhaobiao_search_sample.html").write_bytes(raw)
    for enc in ("utf-8", "gbk", "gb2312"):
        try:
            text = raw.decode(enc)
            if "绿化" in text or "养护" in text or len(text) > 1000:
                print("enc", enc, "len", len(text))
                break
        except Exception:
            continue
    else:
        text = raw.decode("utf-8", "ignore")

    # JS search submit
    for m in re.finditer(r"function\s+headSearchSubmit[\s\S]{0,800}\}", text):
        print("JS", m.group(0)[:500])
    # likely result rows
    patterns = [
        r'<li[^>]*>[\s\S]{0,400}?</li>',
        r'<tr[^>]*>[\s\S]{0,400}?</tr>',
        r'class="[^"]*result[^"]*"',
        r'href="[^"]*info[^"]*\.html"',
        r'href="[^"]*bid_[^"]*\.html"',
    ]
    for pat in patterns:
        ms = re.findall(pat, text, re.I)
        print("PAT", pat, "count", len(ms))
        if ms:
            print(" sample", re.sub(r"\s+", " ", ms[0])[:240])

    hits = []
    for ln in text.splitlines():
        if ("绿化" in ln or "养护" in ln) and "href" in ln.lower():
            hits.append(re.sub(r"\s+", " ", ln.strip())[:240])
    print("HITS", len(hits))
    for h in hits[:15]:
        print(h)

    # top.js may contain search redirect
    top = s.get("https://res.zhaobiao.cn/js/top.js?v=0.1", timeout=30)
    (ROOT / "data" / "web" / "zhaobiao_top.js").write_text(top.text, encoding="utf-8", errors="ignore")
    for m in re.finditer(r"headSearchSubmit|ssearch_q|searchwords|function\s+\w*Search[\s\S]{0,500}", top.text):
        print("TOP", m.group(0)[:300])


if __name__ == "__main__":
    main()
