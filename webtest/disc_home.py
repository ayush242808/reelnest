"""Discover home: instant rows from a saved copy, daily refresh, Indian + anime rows, See all, remembered TMDB host."""
import json, time
exec(open('/home/claude/webtest/features.py').read().split("reset_db()\nwith sync_playwright()")[0])
def mk(prefix, n, mt, extra=None):
    out = []
    for i in range(n):
        r = {"id": 9000 + hash(prefix) % 1000 * 50 + i, "media_type": mt, "poster_path": f"/{prefix}{i}.jpg", "original_language": "hi", "origin_country": ["IN"], "genre_ids": []}
        if mt == "movie": r.update(title=f"{prefix} Movie {i}", release_date="2024-01-01")
        else: r.update(name=f"{prefix} Show {i}", first_air_date="2023-01-01")
        if extra: r.update(extra)
        out.append(r)
    return out
INDIA = {"page": 1, "total_pages": 3, "results": mk("Desi", 8, "movie")}
INDIATV = {"page": 1, "total_pages": 3, "results": mk("Desi", 6, "tv")}
ANIME = {"page": 1, "total_pages": 3, "results": mk("Anime", 7, "tv", {"original_language": "ja", "origin_country": ["JP"], "genre_ids": [16]})}
seen = []; state = {"down": False, "blockdirect": False}
def tm(route):
    u = urlparse(route.request.url); h = u.hostname; q = u.query; seen.append(h + u.path + "?" + q)
    if h in ("image.tmdb.org", "media.themoviedb.org", "wsrv.nl", "images.weserv.nl"): return route.fulfill(status=200, content_type="image/png", body=PNG)
    if state["down"]: return route.abort("connectionreset")
    if state["blockdirect"] and h == "api.themoviedb.org": time.sleep(0); return route.abort("timedout")
    p = u.path
    if "discover/movie" in p and "with_origin_country=IN" in q: data = INDIA
    elif "discover/tv" in p and "with_origin_country=IN" in q: data = INDIATV
    elif "discover/tv" in p and "with_genres=16" in q: data = ANIME
    elif "trending" in p: data = TRENDING
    else: return tmdb(route)
    return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps(data))
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, color_scheme="dark")
    ctx.route("**/*", lambda r: r.abort() if urlparse(r.request.url).hostname == "accounts.google.com" else tm(r) if urlparse(r.request.url).hostname not in (None, "") and "fonts" not in r.request.url else r.continue_())
    pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(APP); pg.evaluate("() => { localStorage.clear(); localStorage.setItem('reelnest.tmdbKey','k'); }"); pg.reload(); pg.wait_for_timeout(300)
    go_discover(pg); pg.wait_for_timeout(600)
    heads = pg.locator(".drow-sec h2").all_inner_texts()
    check("home shows Trending, Indian movies, Indian series and Anime rows", heads == ["Trending this week", "Popular Indian movies", "Popular Indian series", "Popular anime"], heads)
    check("Indian row has Indian movies", pg.locator(".drow-sec", has_text="Popular Indian movies").locator(".dtile").count() == 8 and "India" in pg.locator(".drow-sec", has_text="Popular Indian movies").locator(".dtile").first.inner_text())
    check("anime row labelled Anime", pg.locator(".drow-sec", has_text="Popular anime").locator(".dtile").count() == 7 and "Anime" in pg.locator(".drow-sec", has_text="Popular anime").locator(".dtile").first.inner_text())
    q_india = [s for s in seen if "discover/movie" in s and "with_origin_country=IN" in s]
    check("Indian movies come from TMDB's discover by country IN, by popularity", q_india and "sort_by=popularity.desc" in q_india[0], q_india[:1])
    check("rows scroll sideways, page doesn't", pg.evaluate("(()=>{return [...document.querySelectorAll('.drow')].some(r => r.scrollWidth>r.clientWidth)})()") and no_sideways(pg))
    cache = pg.evaluate("JSON.parse(localStorage.getItem('reelnest.discCache'))")
    check("a copy is saved for next time", cache and cache["v"] == 1 and len(cache["rows"]["anime"]) == 7)
    pg.screenshot(path="/home/claude/webtest/h-home-desktop.png")
    # Reload with the network down: rows appear instantly from the saved copy
    state["down"] = True; seen.clear()
    pg.reload(); t0 = time.time(); pg.evaluate("location.hash='#discover'")
    pg.wait_for_selector(".drow .dtile", timeout=3000); dt = time.time() - t0
    check("after reload, rows show instantly from the saved copy (no network needed)", pg.locator(".dtile").count() == 26 and dt < 1.5, dt)
    check("fresh copy: no catalog requests made", not [s for s in seen if "/3/" in s], seen[:3])
    check("shows when it was updated, with Refresh now", "Updated" in pg.locator("main").inner_text() and pg.locator("[data-act=disc-refresh]").count() == 1)
    # Older than a day: still shown instantly, refreshed in the background
    state["down"] = False; seen.clear()
    pg.evaluate("() => { const c = JSON.parse(localStorage.getItem('reelnest.discCache')); c.at -= 25*3600e3; localStorage.setItem('reelnest.discCache', JSON.stringify(c)); }")
    pg.reload(); pg.evaluate("location.hash='#discover'"); pg.wait_for_selector(".drow .dtile", timeout=3000)
    pg.wait_for_timeout(1200)
    newer = pg.evaluate("JSON.parse(localStorage.getItem('reelnest.discCache')).at") > (time.time() - 3600) * 1000
    check("a copy older than a day is shown, then refreshed in the background", [s for s in seen if "trending" in s] and newer)
    # See all -> grids with pagination
    pg.locator("[data-act=disc-see][data-k=india]").click(); pg.wait_for_timeout(900)
    check("See all Indian movies -> grid filtered to Movies + India", pg.locator(".dgrid .dtile").count() == 8 and "Popular Indian movies" in pg.locator("main").inner_text()
          and pg.locator("[data-act=disc-type][data-v=movie]").get_attribute("aria-pressed") == "true" and pg.locator("[data-act=disc-more]").count() == 1)
    pg.locator("[data-act=disc-clear]").click(); pg.wait_for_timeout(300)
    check("Clear returns to the home rows", pg.locator(".drow-sec").count() == 4)
    pg.locator("[data-act=disc-see][data-k=anime]").click(); pg.wait_for_timeout(900)
    check("See all anime -> anime grid", pg.locator(".dgrid .dtile").count() == 7 and "Popular anime" in pg.locator("main").inner_text())
    pg.locator("[data-act=disc-clear]").click(); pg.wait_for_timeout(300)
    pg.locator("[data-act=disc-see][data-k=trending]").click(); pg.wait_for_timeout(900)
    check("See all trending -> grid with Back to Discover", pg.locator(".dgrid .dtile").count() == 5 and "Back to Discover" in pg.locator("[data-act=disc-clear]").inner_text())
    pg.locator("[data-act=disc-clear]").click(); pg.wait_for_timeout(300)
    # Watchlist + open from a row tile
    row_tile = pg.locator(".drow-sec", has_text="Popular anime").locator(".dtile").first
    row_tile.locator(".dtile-wl").click(); pg.wait_for_timeout(900)
    check("watchlist button works on row tiles", pg.evaluate("Object.values(__reelnest.S.states).some(s => s.watchlist)") and pg.evaluate("__reelnest.UI.detail") is None)
    # Searching still works and goes back to rows when cleared
    pg.locator("#disc-q").fill("idiots"); pg.wait_for_timeout(1200)
    check("search shows a results grid", pg.locator(".dgrid .dtile").count() == 5 and pg.locator(".drow-sec").count() == 0)
    pg.locator("#disc-q").fill(""); pg.wait_for_timeout(800)
    check("clearing search returns to rows", pg.locator(".drow-sec").count() == 4)
    check("no page errors", not errs, errs)
    ctx.close()
    # Remembered host: direct TMDB blocked -> after the first discovery, later loads skip it
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, color_scheme="dark")
    ctx.route("**/*", lambda r: r.abort() if urlparse(r.request.url).hostname == "accounts.google.com" else tm(r) if urlparse(r.request.url).hostname not in (None, "") and "fonts" not in r.request.url else r.continue_())
    pg = ctx.new_page(); pg.goto(APP); pg.evaluate("() => { localStorage.clear(); localStorage.setItem('reelnest.tmdbKey','k'); }")
    state["blockdirect"] = True; pg.reload(); go_discover(pg); pg.wait_for_timeout(1000)
    check("blocked TMDB address: falls back and remembers the working one", pg.evaluate("JSON.parse(localStorage.getItem('reelnest.apiHost')).host") == "https://api.tmdb.org/3/")
    pg.evaluate("localStorage.removeItem('reelnest.discCache')"); seen.clear(); pg.reload(); go_discover(pg); pg.wait_for_timeout(1000)
    first_api = [s for s in seen if "/3/" in s]
    check("next load goes straight to the working address (no wait on the blocked one)", first_api and first_api[0].startswith("api.tmdb.org") and not any(s.startswith("api.themoviedb.org") for s in first_api), first_api[:2])
    ctx.close()
    # phone screenshot
    ctx = b.new_context(viewport={"width": 375, "height": 812}, color_scheme="light", has_touch=True, is_mobile=True)
    ctx.route("**/*", lambda r: r.abort() if urlparse(r.request.url).hostname == "accounts.google.com" else tm(r) if urlparse(r.request.url).hostname not in (None, "") and "fonts" not in r.request.url else r.continue_())
    pg = ctx.new_page(); pg.goto(APP); pg.evaluate("() => { localStorage.clear(); localStorage.setItem('reelnest.tmdbKey','k'); }"); state["blockdirect"] = False
    pg.reload(); go_discover(pg); pg.wait_for_timeout(800)
    check("phone: rows fit, See all reachable, no sideways page scroll", no_sideways(pg) and pg.locator("[data-act=disc-see]").first.bounding_box()["x"] + 40 < 375)
    pg.screenshot(path="/home/claude/webtest/h-home-phone.png"); ctx.close()
    b.close()
print(f"\n{sum(ok)}/{len(ok)} passed")
