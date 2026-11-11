"""Fetch a web page and save it as plain text.
Usage: python3 -I gettext.py URL OUTFILE.txt [keyword ...]
Prints HTTP status, text length, and ~1200 chars of context around each keyword (case-insensitive)."""
import subprocess, sys, re, html
url, out, kws = sys.argv[1], sys.argv[2], sys.argv[3:]
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
r = subprocess.run(["curl", "-sS", "-L", "-m", "40", "-A", UA, "-w", "\n__STATUS__%{http_code}", url], capture_output=True)
raw = r.stdout.decode("utf-8", "ignore"); m = re.search(r"\n__STATUS__(\d+)$", raw)
status = m.group(1) if m else "ERR " + r.stderr.decode()[:200]; raw = raw[:m.start()] if m else raw
t = re.sub(r"<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", raw, flags=re.S | re.I)
t = re.sub(r"<(br|p|div|li|h[1-6]|tr)[^>]*>", "\n", t, flags=re.I)
t = html.unescape(re.sub(r"<[^>]+>", " ", t)); t = re.sub(r"[ \t]+", " ", t); t = re.sub(r"\n\s*\n+", "\n", t)
open(out, "w").write(t)
print(f"status={status} chars={len(t)} saved={out}")
if "Just a moment" in t[:3000]: print("BLOCKED by Cloudflare - use another source")
for k in kws:
    for mm in list(re.finditer(re.escape(k), t, re.I))[:2]:
        print(f"--- [{k}] ---\n{t[max(0, mm.start()-150): mm.start()+1200]}")
