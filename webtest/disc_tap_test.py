"""Tapping the Discover tab again returns to the normal Discover page."""
src = open('/home/claude/webtest/disc_home.py').read()
exec(src.split("with sync_playwright() as p:")[0])
def tab(pg, name): pg.locator(f".side [data-id={name}], .tabbar [data-id={name}]").locator("visible=true").first.click(); pg.wait_for_timeout(500)
def home_rows(pg): return pg.locator(".drow-sec").count()
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    for w, h in ((1280, 900), (390, 844)):
        ctx = b.new_context(viewport={"width": w, "height": h}); ctx.route("**/*", lambda r: r.abort() if urlparse(r.request.url).hostname in ("accounts.google.com",) or (urlparse(r.request.url).hostname or "").endswith("supabase.co") else tm(r) if urlparse(r.request.url).hostname not in (None, "") and "fonts" not in r.request.url else r.continue_())
        pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(APP); pg.evaluate("() => { localStorage.clear(); localStorage.setItem('reelnest.tmdbKey','k'); }"); pg.reload(); pg.wait_for_timeout(300)
        go_discover(pg, search=False); pg.wait_for_timeout(700)
        size = "phone" if w < 500 else "desktop"
        pg.locator("#disc-q").fill("idiots"); pg.wait_for_timeout(1200)
        searched = home_rows(pg) == 0 and pg.locator(".dgrid .dtile").count() > 0
        tab(pg, "discover")
        check(f"[{size}] D1 after a search, tapping Discover shows the normal page", searched and home_rows(pg) == 5 and pg.input_value("#disc-q") == "", (searched, home_rows(pg), pg.input_value("#disc-q")))
        pg.locator(".drow-sec", has_text="Best movies right now").locator("[data-act=disc-see]").click(); pg.wait_for_timeout(800)
        tab(pg, "discover")
        check(f"[{size}] D2 from a See all page too", home_rows(pg) == 5)
        pg.locator("#disc-q").fill("idiots"); pg.wait_for_timeout(1200)
        pg.locator(".dgrid .dtile-open").first.click(); pg.wait_for_timeout(1200)
        on_title = pg.locator("[data-act=back]").count() > 0
        tab(pg, "discover")
        check(f"[{size}] D3 from a title opened from search, the first tap returns to the results", on_title and home_rows(pg) == 0 and pg.input_value("#disc-q") == "idiots", (on_title, home_rows(pg)))
        tab(pg, "discover")
        check(f"[{size}] D3 ...and a second tap shows the normal page", home_rows(pg) == 5 and pg.input_value("#disc-q") == "")
        pg.locator("#disc-q").fill("idiots"); pg.wait_for_timeout(1200); tab(pg, "library"); tab(pg, "discover")
        check(f"[{size}] D4 coming back from another tab keeps your search", pg.input_value("#disc-q") == "idiots" and home_rows(pg) == 0)
        check(f"[{size}] no page errors", not errs, errs[:3])
        ctx.close()
    b.close()
print(f"\n{sum(ok)}/{len(ok)} passed")
