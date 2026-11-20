import json, base64
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAIAAAADCAIAAAA2iEnWAAAAFUlEQVR4nGP4z8DAwMDAxMDAwMAAAAk3AQXcb5r4AAAAAElFTkSuQmCC")
TREND = {"page":1,"total_pages":1,"results":[{"id":1236,"media_type":"tv","name":"JoJo's Bizarre Adventure","original_name":"ジョジョの奇妙な冒険","first_air_date":"2012-10-06","original_language":"ja","origin_country":["JP"],"genre_ids":[16],"poster_path":"/jojo.jpg"}]}
TV = {"id":1236,"name":"JoJo's Bizarre Adventure","original_name":"ジョジョの奇妙な冒険","first_air_date":"2012-10-06","last_air_date":"2022-12-01","episode_run_time":[24],
 "genres":[{"id":16,"name":"Animation"}],"original_language":"ja","origin_country":["JP"],"status":"Returning Series","tagline":"Bizarre is an understatement.",
 "vote_average":8.1,"vote_count":1234,"number_of_seasons":1,"number_of_episodes":2,"poster_path":"/jojo.jpg","backdrop_path":"/bd.jpg",
 "created_by":[{"name":"Hirohiko Araki"}],"networks":[{"name":"Tokyo MX"}],
 "seasons":[{"season_number":1,"name":"Season 1","episode_count":2,"air_date":"2012-10-06"}],
 "credits":{"cast":[{"name":"Kazuyuki Okitsu"}],"crew":[]},"alternative_titles":{"results":[]},
 "content_ratings":{"results":[{"iso_3166_1":"IN","rating":"U/A 16+"}]},
 "videos":{"results":[{"site":"YouTube","type":"Trailer","official":True,"key":"abc123"}]},
 "watch/providers":{"results":{"IN":{"link":"https://x","flatrate":[{"provider_name":"Crunchyroll"},{"provider_name":"Netflix"}]}}},
 "external_ids":{"imdb_id":"tt2359704"}}
SEASON = {"episodes":[{"id":1,"season_number":1,"episode_number":1,"name":"Dio the Invader","air_date":"2012-10-06","runtime":24}]}
ok=[]
def check(n,c,i=""): ok.append(c); print(("PASS " if c else "FAIL ")+n+("" if c else " :: "+str(i)))
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width":1280,"height":900}, color_scheme="dark")
    seen=[]
    def h(route):
        u=route.request.url; host=urlparse(u).hostname; path=urlparse(u).path; seen.append(u)
        if host in ("image.tmdb.org","api.themoviedb.org"): return route.abort("connectionreset")
        if host=="media.themoviedb.org": return route.abort("connectionreset")
        if host=="wsrv.nl": return route.fulfill(status=200, content_type="image/png", body=PNG)
        if host=="api.tmdb.org":
            body = TREND if ("trending" in path or "search" in path) else SEASON if "/season/" in path else TV if "/tv/" in path else {"genres":[]}
            return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin":"*"}, body=json.dumps(body))
        return route.continue_()
    ctx.route("**/*", h)
    pg=ctx.new_page(); errs=[]; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("file:///home/claude/web/index.html"); pg.evaluate("localStorage.setItem('reelnest.tmdbKey','k')")
    pg.goto("file:///home/claude/web/index.html#discover"); pg.reload(); pg.wait_for_timeout(1500)
    pg.locator("#disc-q").fill("x"); pg.wait_for_timeout(1500)
    check("poster loads from fallback image host", pg.locator(".dtile .poster img").count()==1 and "wsrv.nl" in pg.locator(".dtile .poster img").get_attribute("src"))
    check("image host remembered", pg.evaluate("localStorage.getItem('reelnest.imgHost')")=="https://wsrv.nl")
    pg.locator(".dtile .dtile-open").first.click(); pg.wait_for_timeout(1500)
    check("backdrop shown", pg.locator(".detail-hero img.backdrop").count()==1)
    txt = pg.locator(".facts").inner_text()
    check("details card fields", all(k in txt for k in ["Created by","Hirohiko Araki","Network","Tokyo MX","Size","U/A 16+","Last aired"]), txt)
    check("tagline + score", pg.locator(".tagline").count()==1 and "8.1" in pg.locator(".score").inner_text())
    check("trailer + imdb links", pg.locator("a:has-text('Watch trailer')").count()==1 and pg.locator("a:has-text('IMDb page')").count()==1)
    pg.screenshot(path="/home/claude/webtest/12-detail-metadata.png", full_page=True)
    check("no errors", not errs, errs)
    b.close()
print(f"{sum(ok)}/{len(ok)} passed")
