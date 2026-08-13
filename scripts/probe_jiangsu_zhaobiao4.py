from __future__ import annotations

import json
import re
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def main() -> None:
    s = requests.Session()
    s.headers["User-Agent"] = UA
    out = {}
    urls = [
        "https://jiangsu.zhaobiao.cn/ssearch_q_1007_qs_h_s_01_pro_320000_f_03_p_1.html",
        "https://jiangsu.zhaobiao.cn/bid_320000_1_fore.html",
        "https://jiangsu.zhaobiao.cn/bid.html",
        "https://jiangsu.zhaobiao.cn/ssearch_q_%E7%BB%BF%E5%8C%96%E5%85%BB%E6%8A%A4_qs_h_s_01_pro_320000_f_03_p_1.html",
    ]
    for u in urls:
        r = s.get(u, timeout=30)
        items = []
        for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.I | re.S):
            href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2))
            title = re.sub(r"\s+", " ", title).strip()
            if len(title) >= 10:
                items.append({"t": title[:100], "h": href[:180]})
            if len(items) >= 8:
                break
        out[u] = {
            "status": r.status_code,
            "len": len(r.text),
            "need_login": bool(re.search(r"请登录|登录后查看|免费试用", r.text[:8000])),
            "items": items,
        }
    js = s.get(
        "https://user.zhaobiao.cn/resources/scripts/lib/jquery/plugins/login/login_2.js?v=2",
        timeout=30,
    )
    (ROOT / "data" / "web" / "zhaobiao_login2.js").write_text(js.text, encoding="utf-8", errors="ignore")
    out["login_js"] = {
        "status": js.status_code,
        "len": len(js.text),
        "urls": re.findall(r"/ssologin\.do\?method=[a-zA-Z0-9_]+|/[^\"'\s]*captcha[^\"'\s]*", js.text)[:40],
        "has_slider": "slider" in js.text.lower() or "tac" in js.text.lower(),
    }
    path = ROOT / "data" / "web" / "jiangsu_zhaobiao_probe4.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2)[:5000])
    print("WROTE", path)


if __name__ == "__main__":
    main()
