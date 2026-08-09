"""HTTP helper: fetch dealList HTML and grep API patterns."""
import re
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
url = "https://www.ggzy.gov.cn/deal/dealList.html"
req = urllib.request.Request(url, headers={"User-Agent": UA})
with urllib.request.urlopen(req, timeout=30) as r:
    html = r.read().decode("utf-8", "ignore")
print("len", len(html))
for pat in ["dealList", "search", "keyword", "ajax", "api", "query", "/ds/", ".jsp", ".po"]:
    print(pat, len(re.findall(pat, html, re.I)))
scripts = re.findall(r'src=["\']([^"\']+)["\']', html)
print("scripts", scripts[:15])
urls = set()
for m in re.finditer(r'["\'](/[a-zA-Z0-9_./?=&%-]+)["\']', html):
    s = m.group(1)
    if any(k in s.lower() for k in ["deal", "search", "query", "list", "ajax", "information"]):
        urls.add(s)
for u in sorted(urls)[:40]:
    print("rel", u)
# inline ajax patterns
for m in re.finditer(r'url\s*:\s*["\']([^"\']+)["\']', html):
    print("ajax_url", m.group(1)[:150])
