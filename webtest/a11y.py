src = open("/home/claude/webtest/e2e.py").read()
exec(src[: src.index("reset_db()\nwith sync_playwright")])
reset_db()
JS = """() => { const out = [];
  const name = (el) => (el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || el.value || '').trim()
     || (el.id && document.querySelector('label[for="'+el.id+'"]')?.innerText.trim()) || (el.closest('label')?.innerText.trim()) || '';
  for (const el of document.querySelectorAll('button, a[href], input:not([type=hidden]), select, textarea, [role=button]'))
    { const r = el.getBoundingClientRect(); if (r.width && r.height && !name(el)) out.push(el.outerHTML.slice(0, 110)); }
  for (const el of document.querySelectorAll('img:not([alt])')) out.push('img no alt: ' + el.outerHTML.slice(0, 80));
  return out; }"""
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx, pg, errs = new_page(b)
    add_panchayat(pg)
    found = {"detail": pg.evaluate(JS)}
    for t in ("home", "discover", "library", "calendar", "profile"):
        tab(pg, t); found[t] = pg.evaluate(JS)
    for k, v in found.items(): print(k, len(v), v[:4])
    b.close()
