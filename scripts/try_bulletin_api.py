import urllib.request
from pathlib import Path

UID = "e5bc6e1262e5469e8589acd7ed691cf2"
cands = [
    f"https://ctbpsp.com/cutominfoapi/bulletin/{UID}",
    f"https://ctbpsp.com/cutominfoapi/bulletin/bulletinuuid/{UID}",
    f"https://ctbpsp.com/cutominfoapi/bulletinuuid/{UID}",
    f"https://custominfo.cebpubservice.com/cutominfoapi/bulletin/{UID}",
    f"https://ctbpsp.com/cutominfoapi/BulletinPDF/{UID}",
]
lines = []
for u in cands:
    try:
        req = urllib.request.Request(
            u,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://ctbpsp.com/",
                "Accept": "application/json,text/plain,*/*",
            },
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            b = r.read(400)
            lines.append(f"OK {r.status} {u}\n  {b[:300]!r}")
    except Exception as e:
        lines.append(f"ERR {u}\n  {e}")
path = Path(__file__).resolve().parents[1] / "data" / "trial" / "bulletin_api_try.txt"
path.write_text("\n\n".join(lines), encoding="utf-8")
print(path.read_text(encoding="utf-8")[:2000])
