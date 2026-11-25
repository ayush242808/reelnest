src = open("/home/claude/webtest/e2e.py").read()
exec(src[: src.index("reset_db()\nwith sync_playwright")])
reset_db()
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx, pg, errs = new_page(b, w=390, h=844)
    add_panchayat(pg)
    pg.evaluate("() => { __reelnest.setField('tmdb:series:61145', 'status', 'WATCHING'); __reelnest.markEpisodes('tmdb:series:61145', ['tmdb:ep:9001']); }")
    tab(pg, "library"); tab(pg, "home"); pg.wait_for_timeout(500)
    t1 = " ".join(pg.locator(".next-card").first.inner_text().split())
    check("R1 card text is back to the previous version", "1/3 aired · 2 left" in t1 and "of Season" not in t1 and "Whole show" not in t1, t1)
    ring = pg.locator(".next-card .next-side .season-ring").first
    check("R2 a ring under Mark watched shows the season %", ring.count() == 1 and ring.inner_text().strip() == "33%" and ring.get_attribute("aria-label") == "33% of Season 1 watched (1 of 3 episodes)", ring.get_attribute("aria-label") if ring.count() else None)
    def filled(): return pg.evaluate("""() => { const c = document.querySelector('.next-card .season-ring .fill'); if (!c) return 0;
        const C = 2 * Math.PI * 17; return Math.round((1 - parseFloat(c.getAttribute('stroke-dashoffset')) / C) * 100); }""")
    check("R3 the ring is filled to match (33%)", filled() == 33, filled())
    check("R4 the ring is not a button (can't be tapped as 'watched')", pg.evaluate("() => !document.querySelector('.season-ring').closest('button')"))
    pg.locator(".next-card").first.screenshot(path="/tmp/season_ring.png")
    pg.locator(".watch-btn").first.click(); pg.wait_for_timeout(400)
    ring = pg.locator(".next-card .season-ring").first
    check("R5 marking the next episode fills it further (66%)", ring.inner_text().strip() == "66%" and filled() == 67 or filled() == 66, (ring.inner_text(), filled()))
    check("no page errors", not errs, errs[:3])
    b.close()
print(f"\n{sum(1 for r in results if r[1])}/{len(results)} passed")
