from __future__ import annotations

import json
import re
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "web" / "jsggzy_probe2.json"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Safari/537.36"
CTX = ssl._create_unverified_context()


def fetch(url: str, data: bytes | None = None, headers: dict | None = None):
    h = {"User-Agent": UA, "Accept": "*/*"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=40, context=CTX) as resp:
        return resp.status, resp.read(), resp.geturl()


def main():
    report = {}
    list_url = "http://jsggzy.jszwfw.gov.cn/jyxx/tradeInfonew.html"
    st, raw, final = fetch(list_url)
    text = raw.decode("utf-8", "ignore")
    report["list"] = {
        "status": st,
        "final": final,
        "len": len(raw),
        "scripts": re.findall(r'src=[\"\']([^\"\']+\.js)[\"\']', text)[:30],
        "api_candidates": re.findall(r'[\"\'](/[^\"\']*(?:rest|api|search|FullText|trade)[^\"\']*)[\"\']', text, re.I)[:40],
        "head": text[:500],
    }

    # try search page with title param over http
    q = urllib.parse.quote("绿植租摆")
    for u in [
        f"http://jsggzy.jszwfw.gov.cn/jyxx/tradeInfonew.html?title={q}",
        f"http://jsggzy.jszwfw.gov.cn/jyxx/tradeInfonew.html?wd={q}",
    ]:
        try:
            st, raw, final = fetch(u)
            t = raw.decode("utf-8", "ignore")
            report[u] = {"status": st, "len": len(raw), "has": "绿植" in t, "final": final}
        except Exception as e:
            report[u] = {"error": str(e)}

    # intelligent search over http + https unverified
    body = json.dumps(
        {
            "token": "",
            "pn": 0,
            "rn": 10,
            "sdt": "",
            "edt": "",
            "wd": "绿植租摆",
            "inc_wd": "",
            "exc_wd": "",
            "fields": "title",
            "cnum": "001",
            "sort": '{"webdate":"0"}',
            "ssort": "title",
            "cl": 200,
            "terminal": "",
            "condition": [],
            "time": [],
            "highlights": "title",
            "statistics": None,
            "unionCondition": [],
            "accuracy": "",
            "noParticiple": "0",
            "searchRange": None,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    for api in [
        "http://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
        "https://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/esinteligentsearch/getFullTextDataNew",
        "http://jsggzy.jszwfw.gov.cn/inteligentsearch/rest/inteligentSearch/getFullTextDataNew",
    ]:
        try:
            st, raw, final = fetch(
                api,
                data=body,
                headers={
                    "Content-Type": "application/json;charset=UTF-8",
                    "Referer": "http://jsggzy.jszwfw.gov.cn/jyxx/tradeInfonew.html",
                    "Origin": "http://jsggzy.jszwfw.gov.cn",
                },
            )
            j = json.loads(raw.decode("utf-8", "ignore"))
            report[api] = {
                "status": st,
                "keys": list(j.keys())[:20] if isinstance(j, dict) else type(j).__name__,
                "sample": str(j)[:500],
            }
        except Exception as e:
            report[api] = {"error": str(e)}

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("WROTE", OUT)
    print(json.dumps({k: (v.get("status") or v.get("error") or v.get("keys")) for k, v in report.items() if isinstance(v, dict)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
