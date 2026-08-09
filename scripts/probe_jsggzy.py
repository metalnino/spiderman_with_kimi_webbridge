"""Probe Jiangsu public resource trading site for list/search API."""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "web" / "jsggzy_probe.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"


def fetch(url: str, data: bytes | None = None, headers: dict | None = None):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.status, resp.read(), resp.geturl()


def main():
    report = {"tries": []}
    for u in [
        "https://jsggzy.jszwfw.gov.cn/",
        "http://jsggzy.jszwfw.gov.cn/",
    ]:
        try:
            st, raw, final = fetch(u)
            text = raw.decode("utf-8", "ignore")
            links = re.findall(r'href=[\"\']([^\"\']+)[\"\']', text)[:40]
            apiish = [x for x in re.findall(r'[\"\']([^\"\']*(?:api|search|list|trade|notice)[^\"\']*)[\"\']', text, re.I) if len(x) < 200][:40]
            report["tries"].append(
                {
                    "url": u,
                    "status": st,
                    "final": final,
                    "len": len(raw),
                    "title": (re.search(r"<title>([^<]+)", text) or [None, ""])[1],
                    "sample_links": links[:20],
                    "apiish": apiish[:20],
                }
            )
        except Exception as e:
            report["tries"].append({"url": u, "error": str(e)})

    # common新点 / ggzy search endpoints guess
    kw = urllib.parse.quote("绿植租摆")
    guesses = [
        f"https://jsggzy.jszwfw.gov.cn/jyxx/tradeInfonew.html?title={kw}",
        "https://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
        "https://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/inteligentSearch/getFullTextDataNew",
    ]
    for g in guesses:
        try:
            if "getFullTextData" in g:
                body = json.dumps(
                    {
                        "token": "",
                        "pn": 0,
                        "rn": 10,
                        "wd": "绿植租摆",
                        "fields": "title",
                    },
                    ensure_ascii=False,
                ).encode("utf-8")
                st, raw, final = fetch(
                    g,
                    data=body,
                    headers={"Content-Type": "application/json", "Referer": "https://jsggzy.jszwfw.gov.cn/"},
                )
                head = raw[:300].decode("utf-8", "ignore")
                report["tries"].append({"url": g, "status": st, "final": final, "head": head})
            else:
                st, raw, final = fetch(g, headers={"Referer": "https://jsggzy.jszwfw.gov.cn/"})
                text = raw.decode("utf-8", "ignore")
                report["tries"].append(
                    {
                        "url": g,
                        "status": st,
                        "final": final,
                        "len": len(raw),
                        "has_lvzhi": "绿植" in text,
                        "head": text[:200],
                    }
                )
        except Exception as e:
            report["tries"].append({"url": g, "error": str(e)})

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT)
    for t in report["tries"]:
        print(t.get("url"), t.get("status") or t.get("error"), t.get("len") or "")


if __name__ == "__main__":
    main()
