#!/usr/bin/env python3
"""Write (or check) the Content-Security-Policy <meta> tag in index.html.

GitHub Pages can't send custom HTTP headers, so the policy lives in a <meta> tag. The one inline
<script> is allowed by its SHA-256 hash, which changes whenever the script changes:

    python3 tools/csp.py          # update index.html
    python3 tools/csp.py --check  # exit 1 if the tag is missing or stale (run before committing)
"""
import base64, hashlib, re, sys, pathlib

PAGE = pathlib.Path(__file__).resolve().parent.parent / "index.html"
html = PAGE.read_text(encoding="utf-8")
scripts = re.findall(r"<script>([\s\S]*?)</script>", html)
if len(scripts) != 1:
    sys.exit(f"expected exactly one inline <script>, found {len(scripts)}")
h = base64.b64encode(hashlib.sha256(scripts[0].encode("utf-8")).digest()).decode()
policy = "; ".join([
    "default-src 'self'",
    f"script-src 'self' 'sha256-{h}' https://accounts.google.com/gsi/client",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://accounts.google.com/gsi/style",
    "font-src https://fonts.gstatic.com",
    "img-src 'self' https: data: blob:",
    "connect-src 'self' https:",          # Supabase, TMDB, and a user-chosen https relay
    "frame-src https://accounts.google.com/gsi/",
    "worker-src 'self'",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
])
tag = f'<meta http-equiv="Content-Security-Policy" content="{policy}">'
cur = re.search(r'<meta http-equiv="Content-Security-Policy"[^>]*>', html)
if "--check" in sys.argv:
    ok = bool(cur) and cur.group(0) == tag
    print("CSP tag up to date" if ok else "CSP tag missing or stale: run python3 tools/csp.py")
    sys.exit(0 if ok else 1)
html = html.replace(cur.group(0), tag) if cur else html.replace('<meta charset="utf-8">', '<meta charset="utf-8">\n' + tag, 1)
PAGE.write_text(html, encoding="utf-8")
print("CSP updated, script hash sha256-" + h)
