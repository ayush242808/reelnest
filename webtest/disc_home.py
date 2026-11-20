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
OLD_INDIA = {"page": 1, "total_pages": 3, "results": mk("Classic", 5, "movie") + [{"id": 1, "media_type": "movie", "title": "No Poster Film", "release_date": "2001-01-01", "poster_path": None}]}
MOVIES = {"page": 1, "total_pages": 2, "results": mk("World", 6, "movie", {"original_language": "en", "origin_country": ["US"]})}
OLD_MOVIES = {"page": 1, "total_pages": 2, "results": mk("Great", 4, "movie", {"original_language": "en", "origin_country": ["US"]})}
SERIES = {"page": 1, "total_pages": 2, "results": mk("Hit", 5, "tv", {"original_language": "en", "origin_country": ["US"]})}
OLD_SERIES = {"page": 1, "total_pages": 2, "results": mk("Legend", 3, "tv", {"original_language": "en", "origin_country": ["US"]})}
ANIME = {"page": 1, "total_pages": 3, "results": mk("Anime", 7, "tv", {"original_language": "ja", "origin_country": ["JP"], "genre_ids": [16]})}
seen = []; state = {"down": False, "blockdirect": False}
def tm(route):
    u = urlparse(route.request.url); h = u.hostname; q = u.query; seen.append(h + u.path + "?" + q)
    if h in ("image.tmdb.org", "media.themoviedb.org", "wsrv.nl", "images.weserv.nl"): return route.fulfill(status=200, content_type="image/png", body=PNG)
    if state["down"]: return route.abort("connectionreset")
    if state["blockdirect"] and h == "api.themoviedb.org": time.sleep(0); return route.abort("timedout")
    p = u.path
    if "discover/movie" in p and "with_origin_country=IN" in q: data = INDIA if "popularity" in q else OLD_INDIA
    elif "discover/tv" in p and "with_genres=16" in q: data = ANIME
    elif "discover/tv" in p: data = SERIES if "popularity" in q else OLD_SERIES
    elif "discover/movie" in p: data = MOVIES if "popularity" in q else OLD_MOVIES
    elif "trending" in p: data = TRENDING
    else: return tmdb(route)
    return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps(data))
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, color_scheme="dark")
    ctx.route("**/*", lambda r: r.abort() if urlparse(r.request.url).hostname == "accounts.google.com" else tm(r) if urlparse(r.request.url).hostname not in (None, "") and "fonts" not in r.request.url else r.continue_())
    pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(APP); pg.evaluate("() => { localStorage.clear(); localStorage.setItem('reelnest.tmdbKey','k'); }"); pg.reload(); pg.wait_for_timeout(300)
    go_discover(pg, search=False); pg.wait_for_timeout(600)
    heads = pg.locator(".drow-sec h2").all_inner_texts()
    check("home rows: best movies, best series, best Indian movies, anime (no Indian serials row)", heads == ["Best movies right now", "Best series right now", "Best Indian movies", "Popular anime"], heads)
    ind = pg.locator(".drow-sec", has_text="Best Indian movies").locator(".dtile-meta .t").all_inner_texts()
    check("Indian row: recent popular ones first, then older top-rated, no poster-less entries", ind[:8] == [f"Desi Movie {i}" for i in range(8)] and ind[8:] == [f"Classic Movie {i}" for i in range(5)], ind)
    sq = [x for x in seen if "discover/tv" in x and "with_genres=16" not in x]
    check("series exclude soaps, talk, reality, news, kids and anime", sq and all("without_genres=16%2C10762%2C10763%2C10764%2C10766%2C10767" in x for x in sq), sq[:1])
    mq = [x for x in seen if "discover/movie" in x and "with_origin_country" not in x]
    check("movies: recent+popular tier needs rating >= 7 and 150+ votes; older tier >= 7.6 and 2000+ votes",
          any("vote_average.gte=7&" in x and "vote_count.gte=150" in x and "popularity" in x for x in mq) and any("vote_average.gte=7.6" in x and "vote_count.gte=2000" in x and "primary_release_date.desc" in x for x in mq), mq[:2])
    check("best movies row: new first then older greats", pg.locator(".drow-sec", has_text="Best movies right now").locator(".dtile-meta .t").all_inner_texts() == [f"World Movie {i}" for i in range(6)] + [f"Great Movie {i}" for i in range(4)])
    check("anime row unchanged and labelled Anime", pg.locator(".drow-sec", has_text="Popular anime").locator(".dtile").count() == 7 and "Anime" in pg.locator(".drow-sec", has_text="Popular anime").locator(".dtile").first.inner_text())

    check("rows scroll sideways, page doesn't", pg.evaluate("(()=>{return [...document.querySelectorAll('.drow')].some(r => r.scrollWidth>r.clientWidth)})()") and no_sideways(pg))
    cache = pg.evaluate("JSON.parse(localStorage.getItem('reelnest.discCache'))")
    check("a copy is saved for next time", cache and cache["v"] == 2 and len(cache["rows"]["anime"]) == 7)
    pg.screenshot(path="/home/claude/webtest/h-home-desktop.png")
    # Reload with the network down: rows appear instantly from the saved copy
    state["down"] = True; seen.clear()
    pg.reload(); t0 = time.time(); pg.evaluate("location.hash='#discover'")
    pg.wait_for_selector(".drow .dtile", timeout=3000); dt = time.time() - t0
    check("after reload, rows show instantly from the saved copy (no network needed)", pg.locator(".dtile").count() == 10 + 8 + 13 + 7 and dt < 1.5, dt)
    check("fresh copy: no catalog requests made", not [s for s in seen if "/3/" in s], seen[:3])
    check("shows when it was updated, with Refresh now", "Updated" in pg.locator("main").inner_text() and pg.locator("[data-act=disc-refresh]").count() == 1)
    # Older than a day: still shown instantly, refreshed in the background
    state["down"] = False; seen.clear()
    pg.evaluate("() => { const c = JSON.parse(localStorage.getItem('reelnest.discCache')); c.at -= 25*3600e3; localStorage.setItem('reelnest.discCache', JSON.stringify(c)); }")
    pg.reload(); pg.evaluate("location.hash='#discover'"); pg.wait_for_selector(".drow .dtile", timeout=3000)
    pg.wait_for_timeout(1200)
    newer = pg.evaluate("JSON.parse(localStorage.getItem('reelnest.discCache')).at") > (time.time() - 3600) * 1000
    check("a copy older than a day is shown, then refreshed in the background", [s for s in seen if "discover/" in s] and newer)
    # See all -> grids with pagination
    pg.locator("[data-act=disc-see][data-k=india]").click(); pg.wait_for_timeout(900)
    check("See all Indian movies -> same order in a grid, with Load more", pg.locator(".dgrid .dtile").count() == 13 and "Best Indian movies" in pg.locator("main").inner_text() and pg.locator("[data-act=disc-more]").count() == 1)
    pg.locator("[data-act=disc-more]").click(); pg.wait_for_timeout(900)
    check("Load more on a See all page works (no duplicates)", pg.locator(".dgrid .dtile").count() == 13 and not errs, errs)
    pg.locator("[data-act=disc-clear]").click(); pg.wait_for_timeout(300)
    check("Clear returns to the home rows", pg.locator(".drow-sec").count() == 4)
    pg.locator("[data-act=disc-see][data-k=anime]").click(); pg.wait_for_timeout(900)
    check("See all anime -> anime grid with Back to Discover", pg.locator(".dgrid .dtile").count() == 7 and "Popular anime" in pg.locator("main").inner_text() and "Back to Discover" in pg.locator("[data-act=disc-clear]").inner_text())
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
    state["blockdirect"] = True; pg.reload(); go_discover(pg, search=False); pg.wait_for_timeout(1000)
    check("blocked TMDB address: falls back and remembers the working one", pg.evaluate("JSON.parse(localStorage.getItem('reelnest.apiHost')).host") == "https://api.tmdb.org/3/")
    pg.evaluate("localStorage.removeItem('reelnest.discCache')"); seen.clear(); pg.reload(); go_discover(pg, search=False); pg.wait_for_timeout(1000)
    first_api = [s for s in seen if "/3/" in s]
    check("next load goes straight to the working address (no wait on the blocked one)", first_api and first_api[0].startswith("api.tmdb.org") and not any(s.startswith("api.themoviedb.org") for s in first_api), first_api[:2])
    ctx.close()
    # phone screenshot
    ctx = b.new_context(viewport={"width": 375, "height": 812}, color_scheme="light", has_touch=True, is_mobile=True)
    ctx.route("**/*", lambda r: r.abort() if urlparse(r.request.url).hostname == "accounts.google.com" else tm(r) if urlparse(r.request.url).hostname not in (None, "") and "fonts" not in r.request.url else r.continue_())
    pg = ctx.new_page(); pg.goto(APP); pg.evaluate("() => { localStorage.clear(); localStorage.setItem('reelnest.tmdbKey','k'); }"); state["blockdirect"] = False
    pg.reload(); go_discover(pg, search=False); pg.wait_for_timeout(800)
    check("phone: rows fit, See all reachable, no sideways page scroll", no_sideways(pg) and pg.locator("[data-act=disc-see]").first.bounding_box()["x"] + 40 < 375)
    pg.screenshot(path="/home/claude/webtest/h-home-phone.png"); ctx.close()
    b.close()
print(f"\n{sum(ok)}/{len(ok)} passed")
