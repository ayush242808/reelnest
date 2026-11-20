"""Shared relay: visitors with no key browse via the site's relay; own keys go direct first."""
exec(open('/home/claude/webtest/features.py').read().split("reset_db()\nwith sync_playwright()")[0])
RELAY = "gedkntwwjrpfklgvbjtp.supabase.co"
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    for has_key in (False, True):
        ctx, pg, errs = new_page(b)
        hosts = []; urls = []
        pg.on("request", lambda r: (hosts.append(urlparse(r.url).hostname + urlparse(r.url).path), urls.append(r.url)) if "/3/" in r.url else None)
        if not has_key:
            pg.evaluate("() => { localStorage.removeItem('reelnest.tmdbKey'); localStorage.removeItem('reelnest.tmdbAt'); }"); pg.reload(); pg.wait_for_timeout(300)
        go_discover(pg)
        api = [h for h in hosts if "/3/" in h]
        if has_key:
            check("own key: catalog goes straight to TMDB", api and api[0].startswith("api.themoviedb.org"), api[:3])
        if has_key:
            ctx.route("**/api.themoviedb.org/**", lambda r: r.abort("connectionreset")); ctx.route("**/api.tmdb.org/**", lambda r: r.abort("timedout"))
            hosts.clear(); pg.fill("#disc-q", "idiots"); pg.wait_for_timeout(1500)
            via = [h for h in hosts if h.startswith(RELAY)]
            check("own key + TMDB blocked: falls back to the shared relay", via and pg.locator(".dtile").count() > 0, hosts[:4])
            check("own key is never sent to the shared relay", not any("api_key" in u for u in urls if RELAY in u), [u for u in urls if RELAY in u][:2])
        else:
            check("no key: Discover works without entering anything", pg.locator(".dtile").count() == 5 and "Connect the TMDB catalog" not in pg.locator("main").inner_text())
            check("no key: requests go through the shared relay, with no key in the URL", api and all(h.startswith(RELAY + "/functions/v1/tmdb/3/") for h in api), api[:3])
            pg.evaluate("location.hash='#profile'"); pg.wait_for_timeout(300)
            check("profile says no key is needed", "no key is needed" in pg.locator("main").inner_text())
        check("no page errors", not errs, errs); ctx.close()
    b.close()
print(f"\n{sum(ok)}/{len(ok)} passed")
