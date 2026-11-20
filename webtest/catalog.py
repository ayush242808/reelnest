import json
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright
URL = "file:///home/claude/web/index.html"
res = []
def check(n, c, i=""): res.append(c); print(("PASS " if c else "FAIL ") + n + ("" if c else " :: " + str(i)))
TREND = {"page":1,"total_pages":2,"results":[
  {"id":1399,"media_type":"tv","name":"Panchayat","original_name":"पंचायत","first_air_date":"2020-04-03","original_language":"hi","origin_country":["IN"],"genre_ids":[35],"poster_path":"/p.jpg"},
  {"id":7,"media_type":"person","name":"Someone"},
  {"id":550,"media_type":"movie","title":"Jailer","release_date":"2023-08-10","original_language":"ta","genre_ids":[28],"poster_path":"/j.jpg"}]}
TV = {"id":1399,"name":"Panchayat","original_name":"पंचायत","first_air_date":"2020-04-03","episode_run_time":[30],"genres":[{"id":35,"name":"Comedy"}],
  "original_language":"hi","origin_country":["IN"],"status":"Returning Series","seasons":[{"season_number":1,"name":"Season 1","episode_count":2,"air_date":"2020-04-03"}],
  "credits":{"cast":[{"name":"Jitendra Kumar"}]},"alternative_titles":{"results":[]}}
SEASON = {"episodes":[{"id":901,"season_number":1,"episode_number":1,"name":"Gram Panchayat Phulera","air_date":"2020-04-03","runtime":32},
  {"id":902,"season_number":1,"episode_number":2,"name":"Tanki","air_date":"2020-04-03","runtime":30}]}
def body_for(path):
    if "trending" in path or "search" in path: return TREND
    if "/season/" in path: return SEASON
    if "/tv/" in path: return TV
    if "genre" in path: return {"genres":[{"id":35,"name":"Comedy"}]}
    return {}
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    def run(mode):
        ctx = b.new_context(viewport={"width":390,"height":844}, color_scheme="dark")
        seen = []
        def handler(route):
            u = route.request.url; seen.append(u); host = urlparse(u).hostname
            if mode in ("direct-fallback","all-blocked") and host == "api.themoviedb.org": return route.abort("connectionreset")
            if mode == "all-blocked" and host == "api.tmdb.org": return route.abort("timedout")
            if host in ("api.tmdb.org","api.themoviedb.org","relay.test"):
                if host == "relay.test" and urlparse(u).path.startswith("/img/"): return route.fulfill(status=404, body="")
                return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin":"*"}, body=json.dumps(body_for(urlparse(u).path)))
            if host == "image.tmdb.org": return route.fulfill(status=404, body="")
            return route.continue_()
        ctx.route("**/*", handler)
        pg = ctx.new_page(); errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(URL)
        if mode == "relay": pg.evaluate("localStorage.setItem('reelnest.tmdbRelay','https://relay.test')")
        else: pg.evaluate("localStorage.setItem('reelnest.tmdbKey','k123')")
        pg.goto(URL + "#discover"); pg.reload(); pg.wait_for_timeout(1200)
        return ctx, pg, seen, errs
    # 1 direct host blocked -> fallback host works
    ctx, pg, seen, errs = run("direct-fallback")
    check("fallback: trending shows titles (person filtered)", pg.locator(".dtile").count() == 2, pg.locator(".dtile").count())
    check("fallback: used api.tmdb.org with key", any("api.tmdb.org/3/trending" in u and "api_key=k123" in u for u in seen), seen[:4])
    pg.screenshot(path="/home/claude/webtest/09-discover-live.png")
    pg.locator(".dtile .dtile-open").first.click(); pg.wait_for_timeout(1200)
    check("fallback: detail + episodes load", pg.locator("h1", has_text="Panchayat").count()==1 and pg.locator(".ep-row").count()==2, pg.locator(".ep-row").count())
    pg.locator(".check").first.click(); pg.wait_for_timeout(150)
    check("fallback: catalog episode tracked", pg.evaluate("Object.keys(__reelnest.S.states).includes('tmdb:series:1399')"))
    pg.screenshot(path="/home/claude/webtest/10-detail-live.png")
    check("fallback: no page errors", not errs, errs[:2]); ctx.close()
    # 2 relay with no key
    ctx, pg, seen, errs = run("relay")
    check("relay: results via relay without api_key", pg.locator(".dtile").count()==2 and all("api_key" not in u for u in seen if "relay.test/3/" in u) and any("relay.test/3/trending" in u for u in seen), [u for u in seen if 'relay' in u][:3])
    check("relay: posters requested via relay", any("relay.test/img/w342/p.jpg" in u for u in seen))
    ctx.close()
    # 3 everything blocked
    ctx, pg, seen, errs = run("all-blocked")
    check("blocked: clear Jio message with manual add", pg.locator("text=Jio especially").count()==1 and pg.locator("text=Add manually").count()>=1)
    pg.screenshot(path="/home/claude/webtest/11-blocked.png"); ctx.close()
    b.close()
print(f"{sum(res)}/{len(res)} passed")
