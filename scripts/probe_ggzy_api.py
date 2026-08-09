"""Direct API probe for ggzy getTradList."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
API = "https://www.ggzy.gov.cn/information/pubTradingInfo/getTradList"
KEYWORDS = ["绿植租摆", "绿化养护"]


def search(kw: str, page: int = 1) -> dict:
    body = urllib.parse.urlencode({"FINDTXT": kw, "PAGENUMBER": page}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": "https://www.ggzy.gov.cn/deal/dealList.html",
            "Origin": "https://www.ggzy.gov.cn",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    out = {}
    for kw in KEYWORDS:
        try:
            data = search(kw)
            recs = ((data.get("data") or {}).get("records") or []) if data.get("code") == 200 else []
            out[kw] = {
                "code": data.get("code"),
                "message": data.get("message"),
                "total": (data.get("data") or {}).get("total"),
                "pages": (data.get("data") or {}).get("pages"),
                "captcha": data.get("code") == 829,
                "records_sample": recs[:5],
                "record_keys": list(recs[0].keys()) if recs else [],
            }
        except Exception as e:
            out[kw] = {"error": str(e)}
    path = __file__.replace("scripts\\probe_ggzy_api.py", "data\\multi_site\\ggzy_api_probe.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("WROTE", path)
    for kw, v in out.items():
        print(kw, v.get("code"), "total=", v.get("total"), "captcha=", v.get("captcha"))


if __name__ == "__main__":
    main()
