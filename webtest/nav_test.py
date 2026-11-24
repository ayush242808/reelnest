"""Back button, the Continue-watching tick, and Discover hiding watched titles."""
src = open("/home/claude/webtest/e2e.py").read()
exec(src[: src.index("reset_db()\nwith sync_playwright")])

def where(pg):
    if not pg.url.startswith("file://"): return "left app"
    return pg.evaluate("() => (__reelnest.UI.modal ? 'modal:' : '') + (__reelnest.UI.detail ? 'detail' : __reelnest.UI.tab)")
def back(pg): pg.go_back(); pg.wait_for_timeout(350); return where(pg)

reset_db()
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx, pg, errs = new_page(b, w=390, h=844)
    pg.goto("about:blank"); pg.goto(APP); pg.wait_for_timeout(500)   # an entry before the app = "leaving the app"
    add_panchayat(pg)   # Home -> Discover -> title (adds to library)
    check("B1 Back from a title returns to the tab it was opened from", back(pg) == "discover")
    check("B1 Back from a tab goes to Home, not out of the app", back(pg) == "home")
    check("B1 Back from Home leaves the app", back(pg) == "left app")
    pg.goto(APP); pg.wait_for_timeout(500)
    tab(pg, "discover"); tab(pg, "library"); tab(pg, "calendar")
    check("B2 switching tabs doesn't pile up: Back goes straight to Home", back(pg) == "home")
    tab(pg, "library"); pg.locator(".grid .tile").first.click(); pg.wait_for_timeout(600)
    pg.locator("[data-act=back]").first.click(); pg.wait_for_timeout(350)
    check("B3 the on-screen Back button returns to the tab", where(pg) == "library")
    check("B3 ...and the phone Back then goes Home", back(pg) == "home")
    tab(pg, "library"); pg.locator(".grid .tile").first.click(); pg.wait_for_timeout(600); tab(pg, "calendar")
    check("B4 tapping a tab from a title, then Back, goes Home", where(pg) == "calendar" and back(pg) == "home")
    tab(pg, "library"); pg.locator(".grid .tile").first.click(); pg.wait_for_timeout(600)
    pg.evaluate("() => window.scrollTo(0, 0)")
    pg.locator("[data-act=log-movie], [data-act=log-ep], [data-act=menu]").first.click() if pg.locator("[data-act=menu]").count() else None
    pg.evaluate("() => { __reelnest.UI.modal = { kind: 'rules' }; window.dispatchEvent(new Event('resize')); }")
    pg.locator("[data-act=rules]").first.click(); pg.wait_for_timeout(300)
    m1 = where(pg)
    check("B5 Back with a dialog open closes just the dialog", m1.startswith("modal:") and back(pg) == "detail", m1)
    check("B5 ...and the next Back leaves the title", back(pg) == "library")
    pg.goto("about:blank"); pg.goto(APP.split("#")[0] + "#library"); pg.wait_for_timeout(600)
    check("B6 opening the app straight on a tab: Back goes Home", where(pg) == "library" and back(pg) == "home")
    check("B7 Forward works too", (pg.go_forward(), pg.wait_for_timeout(350), where(pg))[2] == "library")
    for i in range(3): tab(pg, "home"); tab(pg, "discover")
    check("B8 many Home/tab switches never trap Back", back(pg) == "home" and back(pg) == "left app")
    pg.goto(APP); pg.wait_for_timeout(500); tab(pg, "library"); pg.locator(".grid .tile").first.click(); pg.wait_for_timeout(600)
    pg.reload(); pg.wait_for_timeout(900)
    check("B9 reloading on a title keeps you there", where(pg) == "detail")
    check("B9 ...and Back still goes title -> tab -> Home -> out", back(pg) == "library" and back(pg) == "home" and back(pg) == "left app")

    # ---- Continue watching tick ----
    pg.goto(APP); pg.wait_for_timeout(500)
    pg.evaluate("() => { __reelnest.setField('tmdb:series:61145', 'status', 'WATCHING'); __reelnest.markEpisodes('tmdb:series:61145', ['tmdb:ep:9001']); }")
    tab(pg, "library"); tab(pg, "home"); pg.wait_for_timeout(300)
    st = pg.evaluate("""() => { const b = document.querySelector('.watch-btn'); if (!b) return null; const r = b.querySelector('.ring');
      const cs = getComputedStyle(r), acc = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
      const tmp = document.createElement('i'); tmp.style.color = acc; document.body.appendChild(tmp); const accRgb = getComputedStyle(tmp).color; tmp.remove();
      return { bg: cs.backgroundColor, border: cs.borderStyle, accRgb, label: b.innerText.trim(), aria: b.getAttribute('aria-label') }; }""")
    check("T1 the Continue-watching button is an empty ring, not the filled 'watched' colour", st and st["bg"] != st["accRgb"] and st["border"] == "dashed", st)
    check("T1 it says what it does", st and st["label"] == "Mark watched" and st["aria"].startswith("Mark S"), st)
    before = pg.evaluate("() => Object.values(__reelnest.S.events).filter(e => e.deletedAt == null).length")
    pg.locator(".watch-btn").first.click(); pg.wait_for_timeout(400)
    check("T2 tapping it still marks the episode watched", pg.evaluate("() => Object.values(__reelnest.S.events).filter(e => e.deletedAt == null).length") == before + 1)

    # ---- Discover hides watched titles ----
    tab(pg, "discover"); pg.wait_for_timeout(1200)
    keys = pg.evaluate("() => [...document.querySelectorAll('.dtile-open')].map(b => b.dataset.key)")
    movie = next((k for k in keys if ":movie:" in k), None)
    pg.evaluate("""(k) => { const S = __reelnest.S; S.works[k] = { id: k, type: 'MOVIE', title: 'Seen it', providerId: k.split(':').pop() };
        __reelnest.ensureState(k); __reelnest.addWatch(k, null, '2026-11-01', false, null); }""", movie)
    tab(pg, "home"); tab(pg, "discover"); pg.wait_for_timeout(500)
    keys2 = pg.evaluate("() => [...document.querySelectorAll('.dtile-open')].map(b => b.dataset.key)")
    check("D1 a movie you've watched disappears from Discover", movie and movie in keys and movie not in keys2, movie)
    title = pg.evaluate("(k) => { const r = Object.values(__reelnest.UI.disc.rows).flat().find(i => i.key === k); return r && r.title; }", movie)
    pg.fill("#disc-q", title); pg.wait_for_timeout(1200)
    keys3 = pg.evaluate("() => [...document.querySelectorAll('.dtile-open')].map(b => b.dataset.key)")
    check("D2 search still finds it", movie in keys3, (title, keys3[:5]))
    pg.fill("#disc-q", ""); pg.wait_for_timeout(600)
    pg.evaluate("(k) => { __reelnest.setField(k, 'status', 'COMPLETED'); }", "tmdb:series:61145")
    tab(pg, "home"); tab(pg, "discover"); pg.wait_for_timeout(400)
    check("D3 a series marked Completed is hidden too", "tmdb:series:61145" not in pg.evaluate("() => [...document.querySelectorAll('.dtile-open')].map(b => b.dataset.key)"))
    check("no page errors", not errs, errs[:3])
    b.close()
print(f"\n{sum(1 for r in results if r[1])}/{len(results)} passed")
