import re
import urllib.request
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0"}
out = Path(__file__).resolve().parents[1] / "data" / "trial" / "api_paths.txt"
lines = []

home = urllib.request.urlopen(
    urllib.request.Request("https://ctbpsp.com/", headers=UA), timeout=25
).read().decode("utf-8", "ignore")
js = re.findall(r'src="([^"]+\.js[^"]*)"', home)
lines.append(f"home_js_count={len(js)}")
for j in js[:30]:
    lines.append("JS " + j)
    url = j if j.startswith("http") else ("https://ctbpsp.com/" + j.lstrip("/"))
    try:
        body = urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=25
        ).read().decode("utf-8", "ignore")
    except Exception as e:
        lines.append(f"  err {e}")
        continue
    paths = sorted(set(re.findall(r"[/]cutominfoapi[^\"'`\s]{0,120}", body)))
    paths += sorted(set(re.findall(r"[/]custominfoapi[^\"'`\s]{0,120}", body)))
    paths += sorted(set(re.findall(r"bulletin[A-Za-z/{}]*", body)))
    for p in paths[:80]:
        lines.append("  " + p)
    # amount related keys
    keys = sorted(set(re.findall(r"[\"'](budget|amount|money|price|投标限价|预算|金额)[\"']", body, re.I)))
    lines.append("  keys=" + ",".join(keys[:40]))

out.write_text("\n".join(lines), encoding="utf-8")
print("WROTE", out, "lines", len(lines))
