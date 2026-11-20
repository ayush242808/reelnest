"""Feature tests: cast photos, Discover tiles, the watch-date calendar, watch sources (movie + episode),
time-zone-safe dates, backup export/import and cloud sync of the new fields. Chrome via Playwright.
TMDB and Supabase are mocked; the Supabase RPCs run against the real schema in a local PostgreSQL."""
import json, subprocess, uuid, io, re, datetime
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from PIL import Image

APP = "file:///home/claude/web/index.html"
SB = "https://test.supabase.co"
ok = []
def check(n, c, info=""):
    ok.append(bool(c)); print(("PASS " if c else "FAIL ") + n + ("" if c else "  :: " + str(info)[:400]))

# ---------- local "Supabase" (real schema) ----------
def psql(sql, db="ft"):
    r = subprocess.run(["psql", "-h", "/tmp", "-p", "5544", "-U", "postgres", "-d", db, "-At", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()
def reset_db():
    subprocess.run(["psql", "-h", "/tmp", "-p", "5544", "-U", "postgres", "-q", "-c", "drop database if exists ft", "-c", "create database ft"], capture_output=True)
    for f in ["/home/claude/webtest/sql/shim.sql", "/home/claude/web/supabase/schema.sql"]:
        r = subprocess.run(["psql", "-h", "/tmp", "-p", "5544", "-U", "postgres", "-d", "ft", "-q", "-v", "ON_ERROR_STOP=1", "-f", f], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
def uid_for(email): return str(uuid.uuid5(uuid.NAMESPACE_DNS, email))
def supabase(route):
    req = route.request; u = urlparse(req.url)
    body = json.loads(req.post_data) if req.post_data else {}
    auth = req.headers.get("authorization", "")
    def okr(obj, status=200): return route.fulfill(status=status, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps(obj))
    if req.method == "OPTIONS": return route.fulfill(status=204, headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*"})
    if u.path.startswith("/auth/v1/otp"): return okr({})
    if u.path == "/auth/v1/verify":
        uid = uid_for(body["email"]); psql(f"insert into auth.users values ('{uid}') on conflict do nothing")
        return okr({"access_token": "tok:" + uid, "refresh_token": "ref:" + uid, "expires_in": 3600, "user": {"id": uid, "email": body["email"]}})
    if u.path == "/auth/v1/token":
        uid = body["refresh_token"].split(":", 1)[1]
        return okr({"access_token": "tok:" + uid, "refresh_token": "ref:" + uid, "expires_in": 3600, "user": {"id": uid}})
    if u.path.startswith("/rest/v1/rpc/"):
        uid = auth.split("tok:", 1)[1]; fn = u.path.rsplit("/", 1)[1]
        pre = f"set role authenticated; select set_config('request.jwt.claim.sub', '{uid}', false);"
        if fn == "rn_pull": return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=psql(pre + f" select rn_pull({int(body['since'])});").splitlines()[-1])
        if fn == "rn_push": psql(pre + " select rn_push($rnj$" + json.dumps(body["payload"]) + "$rnj$::jsonb);"); return okr(1)
    return okr({"msg": "not found"}, 404)

# ---------- TMDB fixtures ----------
buf = io.BytesIO(); Image.new("RGB", (20, 30), (40, 120, 200)).save(buf, "PNG"); PNG = buf.getvalue()
def person(i, name, role, prof): return {"id": 100 + i, "name": name, "character": role, "profile_path": prof}
IDIOTS_CAST = [person(0, "Aamir Khan", "Ranchoddas 'Rancho' Shyamaldas Chanchad", "/aamir.jpg"), person(1, "R. Madhavan", "Farhan Qureshi", "/madhavan.jpg"),
               person(2, "Sharman Joshi", "Raju Rastogi", None), person(3, "Kareena Kapoor", "Pia Sahastrabuddhe", "/broken-kareena.jpg"),
               person(4, "Boman Irani", "Viru Sahastrabuddhe 'Virus'", "/boman.jpg"), person(5, "Omi Vaidya", "Chatur Ramalingam", "/omi.jpg")] + \
              [person(6 + i, f"Supporting Actor {i}", f"Role {i}", f"/s{i}.jpg") for i in range(6)]
IDIOTS = {"id": 20453, "title": "3 Idiots", "original_title": "3 Idiots", "release_date": "2009-12-23", "runtime": 170, "genres": [{"id": 35, "name": "Comedy"}],
          "original_language": "hi", "production_countries": [{"iso_3166_1": "IN"}], "poster_path": "/3i.jpg", "credits": {"cast": IDIOTS_CAST, "crew": []},
          "alternative_titles": {"titles": []}, "release_dates": {"results": []}, "videos": {"results": []}}
IDIOTS_PROV = {"results": {"IN": {"link": "https://www.themoviedb.org/movie/20453/watch?locale=IN",
    "flatrate": [{"provider_id": 8, "provider_name": "Netflix", "logo_path": "/netflix.jpg", "display_priority": 1}, {"provider_id": 119, "provider_name": "Amazon Prime Video", "logo_path": None, "display_priority": 2}],
    "rent": [{"provider_id": 2, "provider_name": "Apple TV", "logo_path": "/apple.jpg", "display_priority": 5}]}}}
DARK = {"id": 70523, "name": "Dark", "original_name": "Dark", "first_air_date": "2017-12-01", "episode_run_time": [55], "genres": [{"id": 18, "name": "Drama"}],
        "original_language": "de", "origin_country": ["DE"], "status": "Ended", "poster_path": "/dark.jpg", "backdrop_path": None,
        "seasons": [{"season_number": 1, "name": "Season 1", "episode_count": 2, "air_date": "2017-12-01"}],
        "credits": {"cast": [{"id": 1, "name": "Louis Hofmann", "character": "", "profile_path": "/louis.jpg"}], "crew": []},
        "aggregate_credits": {"cast": [{"id": 1, "name": "Louis Hofmann", "profile_path": "/louis.jpg", "roles": [{"character": "Jonas Kahnwald"}]},
                                       {"id": 2, "name": "Lisa Vicari", "profile_path": "/lisa.jpg", "roles": [{"character": "Martha Nielsen"}]}]},
        "created_by": [], "networks": [], "alternative_titles": {"results": []}, "content_ratings": {"results": []}, "videos": {"results": []}, "external_ids": {}}
DARK_SEASON = {"episodes": [{"id": 5001, "season_number": 1, "episode_number": 1, "name": "Secrets", "air_date": "2017-12-01", "runtime": 51},
                            {"id": 5002, "season_number": 1, "episode_number": 2, "name": "Lies", "air_date": "2017-12-01", "runtime": 44}]}
OBSCURE = {"id": 777, "title": "Obscure Film", "original_title": "Obscure Film", "release_date": "2019-01-01", "runtime": 95, "genres": [], "original_language": "ml",
           "production_countries": [{"iso_3166_1": "IN"}], "poster_path": None,
           "credits": {"cast": [person(50, "Unknown Performer", "Lead", None), person(51, "Another Newcomer", None, None)], "crew": []},
           "alternative_titles": {"titles": []}, "release_dates": {"results": []}, "videos": {"results": []}}
LONG = "The Extraordinarily Long and Winding Title of a Film That Never Seems to End Anywhere at All"
TRENDING = {"page": 1, "total_pages": 1, "results": [
    {"id": 20453, "media_type": "movie", "title": "3 Idiots", "release_date": "2009-12-23", "original_language": "hi", "origin_country": ["IN"], "genre_ids": [35], "poster_path": "/3i.jpg"},
    {"id": 70523, "media_type": "tv", "name": "Dark", "first_air_date": "2017-12-01", "original_language": "de", "origin_country": ["DE"], "genre_ids": [18], "poster_path": "/dark.jpg"},
    {"id": 777, "media_type": "movie", "title": "Obscure Film", "release_date": "2019-01-01", "original_language": "ml", "genre_ids": [], "poster_path": None},
    {"id": 888, "media_type": "movie", "title": LONG, "release_date": "2021-05-05", "original_language": "en", "genre_ids": [], "poster_path": "/long.jpg"},
    {"id": 30991, "media_type": "tv", "name": "Cowboy Bebop", "first_air_date": "1998-04-03", "original_language": "ja", "origin_country": ["JP"], "genre_ids": [16], "poster_path": "/cb.jpg"}]}
def tmdb(route):
    u = urlparse(route.request.url); h = u.hostname; path = u.path
    if h in ("image.tmdb.org", "media.themoviedb.org", "wsrv.nl", "images.weserv.nl"):
        if "broken" in u.geturl(): return route.fulfill(status=404, body="")
        return route.fulfill(status=200, content_type="image/png", body=PNG)
    p = path.replace("/3/", "/")
    if p.endswith("/tv/70523/watch/providers"): return route.fulfill(status=500, body="")
    data = (IDIOTS_PROV if p.endswith("/movie/20453/watch/providers") else {"results": {}} if p.endswith("/watch/providers")
            else DARK_SEASON if "/tv/70523/season/" in p else DARK if p.startswith("/tv/70523") else IDIOTS if p.startswith("/movie/20453")
            else OBSCURE if p.startswith("/movie/777") else {**OBSCURE, "id": 888, "title": LONG, "poster_path": "/long.jpg"} if p.startswith("/movie/888")
            else {"page": 1, "total_pages": 1, "results": [r for r in TRENDING["results"] if r["media_type"] == ("movie" if "discover/movie" in p else "tv")]} if "discover/" in p
            else TRENDING if ("trending" in p or "search" in p) else {"genres": []})
    return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps(data))

def new_page(b, w=1280, h=900, dark=True, tz="Asia/Kolkata", reduced=False, mobile=False, cloud=False):
    kw = dict(viewport={"width": w, "height": h}, color_scheme="dark" if dark else "light", timezone_id=tz, reduced_motion="reduce" if reduced else "no-preference")
    if mobile: kw.update(has_touch=True, is_mobile=True)
    ctx = b.new_context(**kw)
    ctx.route("**/*", lambda r: r.abort() if urlparse(r.request.url).hostname == "accounts.google.com" else supabase(r) if urlparse(r.request.url).hostname == "test.supabase.co"
              else tmdb(r) if urlparse(r.request.url).hostname not in (None, "") and "fonts" not in r.request.url else r.continue_())
    pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(APP)
    pg.evaluate(f"""() => {{ localStorage.clear(); localStorage.setItem('reelnest.tmdbKey','k');
        localStorage.setItem('reelnest.sbUrl', {json.dumps(SB if cloud else 'https://off.invalid')}); localStorage.setItem('reelnest.sbKey', {json.dumps('anon-public-key-for-tests-0123456789' if cloud else 'x')}); }}""")
    pg.reload(); pg.wait_for_timeout(300)
    return ctx, pg, errs
def go_discover(pg, search=True):
    pg.evaluate("location.hash='#discover'"); pg.wait_for_timeout(900)
    if search: pg.locator("#disc-q").fill("top"); pg.wait_for_timeout(1300)
def open_tile(pg, title):
    pg.locator(".dtile .dtile-open", has_text=title).first.click(); pg.wait_for_timeout(1300)
def no_sideways(pg): return pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
def events(pg, key): return pg.evaluate(f"Object.values(__reelnest.S.events).filter(e => e.workId === {json.dumps(key)})")
def active(pg, key): return [e for e in events(pg, key) if e["deletedAt"] is None]
T = datetime.date.today()
fmt = lambda d: f"{d.day} {d.strftime('%b')} {d.year}"  # en-US locale prints "Mar 5, 2024"; we compare via the app's own formatter instead
def app_fmt(pg, iso): return pg.evaluate(f"(() => {{ const [y,m,d] = {json.dumps(iso)}.split('-').map(Number); return new Date(y, m-1, d).toLocaleDateString(undefined, {{day:'numeric', month:'short', year:'numeric'}}); }})()")

reset_db()
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])

    # ================= 1. CAST =================
    ctx, pg, errs = new_page(b)
    go_discover(pg); open_tile(pg, "3 Idiots")
    cards = pg.locator(".cast")
    check("cast: 3 Idiots shows 12 portrait cards", cards.count() == 12, cards.count())
    first = cards.nth(0)
    check("cast: real name + character under it", "Aamir Khan" in first.inner_text() and "Rancho" in first.locator(".cast-role").inner_text(), first.inner_text())
    pg.wait_for_timeout(800)
    img = first.locator("img")
    check("cast: actor photo loaded with the actor's name as alt text", img.count() == 1 and img.get_attribute("alt") == "Aamir Khan" and pg.evaluate("(el) => el.naturalWidth > 0", img.element_handle()))
    check("cast: photo uses a profile-size image (w185) and lazy loading", "w185" in (img.get_attribute("src") or "") and img.get_attribute("loading") == "lazy", img.get_attribute("src"))
    sj = cards.nth(2)
    check("cast: no photo -> initials placeholder, no image", sj.locator("img").count() == 0 and sj.locator(".ini").inner_text().strip() == "SJ")
    kk = cards.nth(3)
    check("cast: failed photo -> placeholder only (never another person's photo)", kk.locator("img").count() == 0 and kk.locator(".ini").is_visible(), kk.inner_html()[:200])
    row = pg.locator(".cast-row")
    check("cast: row scrolls horizontally", pg.evaluate("(el) => el.scrollWidth > el.clientWidth", row.element_handle()))
    pg.locator("[data-act=cast-scroll][data-dir='1']").click(); pg.wait_for_timeout(700)
    check("cast: scroll button moves the row", pg.evaluate("(el) => el.scrollLeft > 0", row.element_handle()))
    check("cast: row is keyboard-focusable and labelled", row.get_attribute("tabindex") == "0" and row.get_attribute("aria-labelledby"))
    check("cast: page doesn't scroll sideways (desktop)", no_sideways(pg))
    pg.screenshot(path="/home/claude/webtest/f1-cast-desktop-dark.png", full_page=False, clip={"x": 236, "y": 0, "width": 1044, "height": 900})
    pg.locator(".cast-row").scroll_into_view_if_needed(); pg.wait_for_timeout(300)
    pg.screenshot(path="/home/claude/webtest/f1-cast-row.png")
    # international show: characters from aggregate credits
    pg.locator("[data-act=back]").click(); pg.wait_for_timeout(300); open_tile(pg, "Dark")
    check("cast: international series shows character from all seasons", "Jonas Kahnwald" in pg.locator(".cast").first.inner_text(), pg.locator(".cast").first.inner_text())
    # missing photos
    pg.locator("[data-act=back]").click(); pg.wait_for_timeout(300); open_tile(pg, "Obscure Film")
    c2 = pg.locator(".cast")
    check("cast: title with no photos shows placeholders and no photo credit", c2.count() == 2 and pg.locator(".cast img").count() == 0 and "Photos from TMDB" not in pg.locator("main").inner_text())
    check("cast: missing character is simply omitted", c2.nth(1).locator(".cast-role").count() == 0)
    # legacy names-only cast is refreshed once
    pg.evaluate("""() => { const R = __reelnest; R.S.works['tmdb:movie:20453'].cast = ['Aamir Khan', 'R. Madhavan']; R.S.works['tmdb:movie:20453'].fetchedAt = Date.now(); }""")
    pg.locator("[data-act=back]").click(); pg.wait_for_timeout(200); open_tile(pg, "3 Idiots"); pg.wait_for_timeout(600)
    check("cast: titles saved with names only get photos on next open", pg.evaluate("typeof __reelnest.S.works['tmdb:movie:20453'].cast[0] === 'object'") and pg.locator(".cast").count() == 12)
    check("no page errors (cast)", not errs, errs); ctx.close()

    ctx, pg, errs = new_page(b, 375, 812, mobile=True)
    go_discover(pg); open_tile(pg, "3 Idiots")
    pg.locator(".cast-row").scroll_into_view_if_needed(); pg.wait_for_timeout(500)
    check("cast: phone - row scrolls, page doesn't", pg.evaluate("(el) => el.scrollWidth > el.clientWidth", pg.locator(".cast-row").element_handle()) and no_sideways(pg))
    pg.screenshot(path="/home/claude/webtest/f1-cast-mobile.png")
    ctx.close()

    # ================= 2. DISCOVER TILES =================
    ctx, pg, errs = new_page(b)
    go_discover(pg, search=False)
    check("tiles: Discover home shows poster rows", pg.locator(".drow .dtile").count() >= 4 and pg.locator(".result").count() == 0)
    pg.locator("#disc-q").fill("top"); pg.wait_for_timeout(1300)
    tiles = pg.locator(".dtile")
    check("tiles: results render as poster tiles", tiles.count() == 5, tiles.count())
    t0 = tiles.nth(0).inner_text()
    check("tiles: title, year and type label", "3 Idiots" in t0 and "2009" in t0 and "Movie" in t0, t0)
    check("tiles: series and anime labels", "Series" in tiles.nth(1).inner_text() and "Anime" in tiles.nth(4).inner_text())
    check("tiles: language/country line", "Hindi" in t0 and "India" in t0, t0)
    obs = tiles.nth(2)
    check("tiles: missing poster -> designed fallback", obs.locator(".poster img").count() == 0 and obs.locator(".ph").is_visible())
    lt = tiles.nth(3).locator(".dtile-meta .t")
    lh = pg.evaluate("(el) => parseFloat(getComputedStyle(el).lineHeight)", lt.element_handle())
    check("tiles: long title clamped to two lines", lt.bounding_box()["height"] <= lh * 2 + 2, (lt.bounding_box()["height"], lh))
    tiles = pg.locator(".dtile")
    cols = pg.evaluate("getComputedStyle(document.querySelector('.dgrid')).gridTemplateColumns.split(' ').length")
    check("tiles: 'See all' opens a desktop grid with 5+ columns", cols >= 5 and tiles.count() == 5, cols)
    # watchlist button
    wl = tiles.nth(0).locator(".dtile-wl")
    wl.click(); pg.wait_for_timeout(900)
    check("tiles: watchlist button adds without opening the title", pg.evaluate("__reelnest.UI.detail") is None and pg.evaluate("!!__reelnest.S.states['tmdb:movie:20453']?.watchlist"))
    check("tiles: watchlist state is shown (pressed + badge)", tiles.nth(0).locator(".dtile-wl").get_attribute("aria-pressed") == "true" and "Watchlist" in tiles.nth(0).locator(".dtile-badge").inner_text())
    tiles.nth(0).locator(".dtile-wl").click(); pg.wait_for_timeout(400)
    check("tiles: pressing again removes it (still in library badge)", pg.evaluate("__reelnest.S.states['tmdb:movie:20453'].watchlist") is False and "In library" in tiles.nth(0).locator(".dtile-badge").inner_text())
    pg.locator(".toast [data-act=undo]").click(); pg.wait_for_timeout(200)
    check("tiles: undo restores watchlist", pg.evaluate("__reelnest.S.states['tmdb:movie:20453'].watchlist") is True)
    # hover tilt
    bb = tiles.nth(1).bounding_box()
    pg.mouse.move(bb["x"] + bb["width"] * 0.85, bb["y"] + bb["height"] * 0.2); pg.wait_for_timeout(120)
    pg.mouse.move(bb["x"] + bb["width"] * 0.9, bb["y"] + bb["height"] * 0.15); pg.wait_for_timeout(500)
    ry = pg.evaluate("document.querySelectorAll('.dtile')[1].style.getPropertyValue('--ry')")
    tr = pg.evaluate("getComputedStyle(document.querySelectorAll('.dtile')[1]).transform")
    check("tiles: hover tilts toward the pointer and lifts", ry not in ("", "0.00deg") and tr != "none", (ry, tr))
    glow = pg.evaluate("getComputedStyle(document.querySelectorAll('.dtile')[1].querySelector('.poster')).boxShadow")
    check("tiles: hover adds a soft shadow/glow", "rgba" in glow or "rgb" in glow, glow)
    pg.screenshot(path="/home/claude/webtest/f2-discover-hover-dark.png")
    pg.mouse.move(5, 5); pg.wait_for_timeout(600)
    check("tiles: tilt resets when the pointer leaves", pg.evaluate("document.querySelectorAll('.dtile')[1].style.getPropertyValue('--ry')") == "")
    # keyboard
    pg.locator("#disc-q").focus()
    found = None
    for i in range(14):
        pg.keyboard.press("Tab")
        cls = pg.evaluate("document.activeElement.className")
        if "dtile-open" in cls: found = i; break
    sh = pg.evaluate("getComputedStyle(document.activeElement.querySelector('.poster')).boxShadow")
    check("tiles: keyboard focus reaches the tile with a visible ring", found is not None and sh != "none", sh)
    pg.keyboard.press("Tab")
    check("tiles: next Tab stop is the tile's watchlist button with a label", "dtile-wl" in pg.evaluate("document.activeElement.className") and "watchlist" in pg.evaluate("document.activeElement.getAttribute('aria-label')"))
    pg.keyboard.press("Enter"); pg.wait_for_timeout(900)
    check("tiles: Enter on the watchlist button doesn't open the title", pg.evaluate("__reelnest.UI.detail") is None)
    # search + manual entry still there
    pg.locator("#disc-q").fill("idiots"); pg.wait_for_timeout(1200)
    check("tiles: search results use tiles too", pg.locator(".dtile").count() == 5)
    check("tiles: manual entry still offered", pg.locator("[data-act=manual]").count() >= 1)
    check("no page errors (discover desktop)", not errs, errs); ctx.close()

    ctx, pg, errs = new_page(b, 1280, 900, reduced=True)
    go_discover(pg); bb = pg.locator(".dtile").nth(1).bounding_box()
    pg.mouse.move(bb["x"] + bb["width"] * 0.85, bb["y"] + 30); pg.wait_for_timeout(120); pg.mouse.move(bb["x"] + bb["width"] * 0.9, bb["y"] + 40); pg.wait_for_timeout(400)
    tr = pg.evaluate("getComputedStyle(document.querySelectorAll('.dtile')[1]).transform")
    glow = pg.evaluate("getComputedStyle(document.querySelectorAll('.dtile')[1].querySelector('.poster')).boxShadow")
    check("tiles: reduced motion -> no tilt/lift, static highlight instead", tr == "none" and "rgb" in glow, (tr, glow))
    ctx.close()

    for (w, h, name, mn) in [(820, 1180, "tablet", 4), (375, 812, "phone", 2)]:
        ctx, pg, errs = new_page(b, w, h, mobile=(w < 800), dark=(w > 800))
        go_discover(pg)
        cols = pg.evaluate("getComputedStyle(document.querySelector('.dgrid')).gridTemplateColumns.split(' ').length")
        check(f"tiles: {name} layout has {mn}+ columns, no sideways scroll", cols >= mn and no_sideways(pg), cols)
        if w < 800:
            check("tiles: touch - watchlist button and labels visible without hover", pg.locator(".dtile-wl").first.is_visible() and pg.locator(".dtile-meta .t").first.is_visible())
            pg.screenshot(path="/home/claude/webtest/f2-discover-phone-light.png")
        else:
            pg.screenshot(path="/home/claude/webtest/f2-discover-tablet-dark.png")
        check(f"no page errors ({name})", not errs, errs); ctx.close()
    ctx, pg, errs = new_page(b, 1280, 900, dark=False); go_discover(pg)
    pg.screenshot(path="/home/claude/webtest/f2-discover-desktop-light.png"); ctx.close()

    # ================= 3. CALENDAR + 4. SOURCES (movie) =================
    ctx, pg, errs = new_page(b)
    go_discover(pg); open_tile(pg, "3 Idiots"); pg.wait_for_timeout(500)
    K = "tmdb:movie:20453"
    pg.locator("[data-act=movie-watch]").click(); pg.wait_for_timeout(500)
    check("calendar: dialog opens with themed field (no native date input)", pg.locator("#overlay input[type=date]").count() == 0 and pg.locator("#wd-input").is_visible())
    check("calendar: field shows today by default", pg.locator("#wd-input").input_value() == app_fmt(pg, T.isoformat()))
    pg.locator("#wd-input").click(); pg.wait_for_timeout(300)
    check("calendar: clicking the field opens the calendar", pg.locator(".cal").is_visible())
    ttl = pg.locator(".cal-title").inner_text()
    check("calendar: month and year heading", str(T.year) in ttl, ttl)
    check("calendar: seven-column grid with weekday labels", pg.locator(".cal-grid th").count() == 7)
    tday = pg.locator(f"#cal-d-{T.isoformat()}")
    check("calendar: today marked (and selected)", "today" in tday.get_attribute("class") and tday.get_attribute("aria-current") == "date" and tday.get_attribute("aria-pressed") == "true")
    check("calendar: next month disabled (no future watches)", pg.locator(".cal-head [data-act=cal-nav][data-n='1']").is_disabled())
    nxt = T + datetime.timedelta(days=1)
    if nxt.month == T.month: check("calendar: future days disabled", pg.locator(f"#cal-d-{nxt.isoformat()}").is_disabled())
    # no overlap with rewatch / sources / save
    cal = pg.locator(".cal").bounding_box()
    def overlaps(a, bx): return not (a["y"] + a["height"] <= bx["y"] or bx["y"] + bx["height"] <= a["y"] or a["x"] + a["width"] <= bx["x"] or bx["x"] + bx["width"] <= a["x"])
    others = [pg.locator("label:has(#wd-re)"), pg.locator(".src-group"), pg.locator("[data-act=watch-save]")]
    check("calendar: doesn't cover rewatch, sources or Save", all(not overlaps(cal, o.bounding_box()) for o in others))
    check("calendar: fits inside the viewport width", cal["x"] >= 0 and cal["x"] + cal["width"] <= 1280)
    pg.screenshot(path="/home/claude/webtest/f3-calendar-dark.png")
    # keyboard: focus on a day, arrows move
    pg.locator(f"#cal-d-{T.isoformat()}").focus(); pg.keyboard.press("ArrowLeft"); pg.wait_for_timeout(150)
    y1 = (T - datetime.timedelta(days=1)).isoformat()
    check("calendar: arrow keys move between days", pg.evaluate("document.activeElement.id") == f"cal-d-{y1}", pg.evaluate("document.activeElement.id"))
    pg.keyboard.press("PageUp"); pg.wait_for_timeout(150)
    check("calendar: PageUp goes to the previous month", pg.evaluate("document.activeElement.id").startswith("cal-d-") and pg.locator(".cal-title").inner_text() != ttl)
    # Escape closes calendar only
    pg.keyboard.press("Escape"); pg.wait_for_timeout(200)
    check("calendar: Escape closes the calendar, not the dialog", pg.locator(".cal").count() == 0 and pg.locator("#wd-input").is_visible())
    check("calendar: focus returns to the calendar button", pg.evaluate("document.activeElement.id") == "wd-toggle")
    # month/year picker for old dates
    pg.locator("#wd-toggle").click(); pg.wait_for_timeout(200)
    pg.locator(".cal-title").click(); pg.wait_for_timeout(200)
    pg.locator("#cal-year-sel").select_option("2015"); pg.wait_for_timeout(200)
    pg.locator(".cal-months [data-ym='2015-02']").click(); pg.wait_for_timeout(200)
    check("calendar: month/year picker jumps to Feb 2015", "2015" in pg.locator(".cal-title").inner_text())
    pg.screenshot(path="/home/claude/webtest/f3-calendar-feb2015.png")
    pg.locator("#cal-d-2015-02-14").click(); pg.wait_for_timeout(200)
    check("calendar: picking a date fills the field and closes", pg.locator("#wd-input").input_value() == app_fmt(pg, "2015-02-14") and pg.locator(".cal").count() == 0)
    check("calendar: picking a date doesn't save anything yet", len(active(pg, K)) == 0)
    pg.locator("[data-act=modal-close]").click(); pg.wait_for_timeout(200)
    check("calendar: Cancel closes without changing history", pg.locator("#overlay .sheet").count() == 0 and len(active(pg, K)) == 0)
    # typed date + Today shortcut + invalid
    pg.locator("[data-act=movie-watch]").click(); pg.wait_for_timeout(300)
    pg.locator("#wd-input").fill("31/02/2024"); pg.keyboard.press("Enter"); pg.wait_for_timeout(150)
    check("calendar: impossible typed date is rejected with a message", "couldn't be read" in pg.locator("#wd-hint").inner_text())
    pg.locator("#wd-input").fill("05/03/2024"); pg.keyboard.press("Tab"); pg.wait_for_timeout(150)
    check("calendar: typed 05/03/2024 reads as 5 March 2024", pg.locator("#wd-input").input_value() == app_fmt(pg, "2024-03-05"), pg.locator("#wd-input").input_value())
    # sources: order, logos, labels, note
    labels = pg.locator(".src").all_inner_texts()
    check("source: options in order Theater, OTT…, Other platform, Unofficial last", labels[0] == "Theater" and labels[-2] == "Other platform" and labels[-1] == "Unofficial"
          and labels[1:4] == ["Netflix", "Amazon Prime Video", "Apple TV"], labels)
    check("source: every option has an icon/logo and visible text", all(pg.locator(".src").nth(i).locator(".src-ico svg, .src-ico img").count() >= 1 for i in range(len(labels))))
    check("source: OTT logo comes from the provider data; no logo -> neutral icon", pg.locator(".src", has_text="Netflix").locator("img").count() == 1 and pg.locator(".src", has_text="Amazon Prime Video").locator("img").count() == 0)
    check("source: OTT list labelled as current availability", "Listed in India now" in pg.locator(".src-group").inner_text())
    check("source: Unofficial uses the skull-and-crossbones icon", pg.locator(".src.unofficial svg circle").count() == 2)
    check("source: radio semantics", pg.locator("[role=radiogroup] [role=radio]").count() == len(labels))
    pg.locator(".src", has_text="Netflix").click(); pg.wait_for_timeout(150)
    check("source: selected option highlighted", pg.locator(".src", has_text="Netflix").get_attribute("aria-checked") == "true")
    pg.screenshot(path="/home/claude/webtest/f4-source-dialog-dark.png")
    pg.locator("[data-act=watch-save]").click(); pg.wait_for_timeout(300)
    ev = active(pg, K)
    check("source: movie watch saved with date + Netflix", len(ev) == 1 and ev[0]["watchedDate"] == "2024-03-05" and ev[0]["source"]["name"] == "Netflix" and ev[0]["source"]["kind"] == "ott", ev)
    check("source: history shows the source with its logo", "Netflix" in pg.locator(".hist").inner_text() and pg.locator(".hist .src-tag img").count() == 1)
    # rewatch with a different source
    pg.locator("[data-act=movie-watch]").click(); pg.wait_for_timeout(300)
    check("rewatch: second watch defaults to rewatch", pg.locator("#wd-re").is_checked())
    pg.locator(".src", has_text="Theater").click(); pg.locator("[data-act=watch-save]").click(); pg.wait_for_timeout(300)
    ev = sorted(active(pg, K), key=lambda e: e["watchedAt"])
    check("rewatch: recorded with a different source", len(ev) == 2 and ev[1]["isRewatch"] and ev[1]["source"]["kind"] == "theater" and ev[0]["source"]["name"] == "Netflix", ev)
    # edit first watch -> Other platform
    first_id = ev[0]["id"]
    pg.locator(f"[data-act=watch-edit][data-ev='{first_id}']").click(); pg.wait_for_timeout(300)
    check("edit: dialog prefilled with date and source", pg.locator("#wd-input").input_value() == app_fmt(pg, "2024-03-05") and pg.locator(".src", has_text="Netflix").get_attribute("aria-checked") == "true")
    pg.locator(".src", has_text="Other platform").click(); pg.wait_for_timeout(150)
    pg.locator("[data-act=watch-save]").click(); pg.wait_for_timeout(200)
    check("edit: Other platform requires a name", pg.locator("#overlay .sheet").count() == 1)
    pg.locator("#src-other").fill("Zee5"); pg.locator("[data-act=watch-save]").click(); pg.wait_for_timeout(300)
    ev = active(pg, K); edited = [e for e in ev if e["source"] and e["source"]["kind"] == "other"]
    check("edit: source changed, date kept, still 2 watches", len(ev) == 2 and len(edited) == 1 and edited[0]["source"]["name"] == "Zee5" and edited[0]["watchedDate"] == "2024-03-05", ev)
    # clear a source
    pg.locator(f"[data-act=watch-edit][data-ev='{edited[0]['id']}']").click(); pg.wait_for_timeout(300)
    pg.locator("[data-act=src-clear]").click(); pg.locator("[data-act=watch-save]").click(); pg.wait_for_timeout(300)
    check("edit: source can be cleared", any(e["source"] is None and e["watchedDate"] == "2024-03-05" for e in active(pg, K)))
    # unofficial
    pg.locator("[data-act=movie-watch]").click(); pg.wait_for_timeout(300)
    pg.locator(".src.unofficial").click(); pg.locator("[data-act=watch-save]").click(); pg.wait_for_timeout(300)
    check("source: Unofficial saved and shown with its icon", any(e["source"] and e["source"]["kind"] == "unofficial" for e in active(pg, K)) and "Unofficial" in pg.locator(".hist").inner_text())
    # no source at all
    pg.locator("[data-act=movie-watch]").click(); pg.wait_for_timeout(300); pg.locator("[data-act=watch-save]").click(); pg.wait_for_timeout(300)
    check("source: optional - saved without one", sum(1 for e in active(pg, K) if e["source"] is None) == 2)
    pg.locator(".hist").scroll_into_view_if_needed(); pg.screenshot(path="/home/claude/webtest/f4-history-dark.png")
    # persistence after refresh
    pg.wait_for_timeout(700); pg.reload(); pg.wait_for_timeout(500)
    pg.evaluate(f"__reelnest.UI.detail = {json.dumps(K)}"); pg.evaluate("location.hash='#library'"); pg.wait_for_timeout(300)
    pg.locator(".tile, .row", has_text="3 Idiots").first.click(); pg.wait_for_timeout(800)
    ev2 = active(pg, K)
    check("persist: dates and sources survive a refresh", len(ev2) == 4 and {(e["watchedDate"], (e["source"] or {}).get("kind")) for e in ev2} >= {("2024-03-05", None), (T.isoformat(), "theater"), (T.isoformat(), "unofficial")}, ev2)
    check("persist: history shows 5 Mar 2024 after refresh", app_fmt(pg, "2024-03-05") in pg.locator(".hist").inner_text())
    backup = pg.evaluate("__reelnest.exportJson()")
    bj = json.loads(backup)
    check("backup: export includes watch dates and sources", any(e.get("source") and e["source"]["kind"] == "theater" for e in bj["events"]) and all("watchedDate" in e for e in bj["events"]))
    check("no page errors (movie watch)", not errs, errs); ctx.close()

    # ---- light theme calendar look ----
    ctx, pg, errs = new_page(b, 1280, 900, dark=False)
    go_discover(pg); open_tile(pg, "3 Idiots"); pg.locator("[data-act=movie-watch]").click(); pg.wait_for_timeout(300)
    try: pg.locator("#wd-toggle").click(timeout=4000)
    except Exception as e:
        print("DEBUG", pg.evaluate("(()=>{const r=document.getElementById('wd-toggle').getBoundingClientRect(); const el=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2); return [r.x,r.y,r.width,r.height, el && el.outerHTML.slice(0,160), innerWidth, innerHeight, JSON.stringify(document.querySelector('.sheet').getBoundingClientRect())]})()"))
        pg.screenshot(path="/tmp/dbg-fail.png"); raise
    pg.wait_for_timeout(300)
    pg.screenshot(path="/home/claude/webtest/f3-calendar-light.png"); ctx.close()
    # ---- phone calendar ----
    ctx, pg, errs = new_page(b, 375, 812, mobile=True)
    go_discover(pg); open_tile(pg, "3 Idiots"); pg.locator("[data-act=movie-watch]").click(); pg.wait_for_timeout(300); pg.locator("#wd-toggle").click(); pg.wait_for_timeout(300)
    cal = pg.locator(".cal").bounding_box(); btn = pg.locator(".cal-day-btn").first.bounding_box()
    check("calendar: phone - fits the screen with 40px+ tap targets", cal["x"] >= 0 and cal["x"] + cal["width"] <= 375 and btn["height"] >= 40, (cal, btn))
    pg.screenshot(path="/home/claude/webtest/f3-calendar-phone.png")
    check("no page errors (phone calendar)", not errs, errs); ctx.close()

    # ================= 4b. EPISODES + missing provider data =================
    ctx, pg, errs = new_page(b)
    go_discover(pg); open_tile(pg, "Dark"); pg.wait_for_timeout(900)
    D = "tmdb:series:70523"; E1 = "tmdb:ep:5001"
    pg.locator(f".ep-row:has([data-ep='{E1}']) [data-act=menu]").click(); pg.wait_for_timeout(150)
    pg.locator(f"[data-act=watch-ep-new][data-ep='{E1}']").click(); pg.wait_for_timeout(700)
    note = pg.locator(".src-group").inner_text()
    check("episode: dialog names the episode", "S01E01" in pg.locator("#overlay .sheet").inner_text())
    check("missing provider data: Theater, Other platform, Unofficial still offered", all(pg.locator(".src", has_text=x).count() == 1 for x in ["Theater", "Other platform", "Unofficial"]))
    check("missing provider data: no claim that nothing is available", "Couldn't load the current platform list" in note and "no platforms" not in note.lower(), note)
    pg.locator("#wd-input").fill("2 Jan 2018"); pg.keyboard.press("Tab")
    pg.locator(".src.unofficial").click(); pg.locator("[data-act=watch-save]").click(); pg.wait_for_timeout(300)
    ev = active(pg, D)
    check("episode: watch saved with date + source", len(ev) == 1 and ev[0]["episodeId"] == E1 and ev[0]["watchedDate"] == "2018-01-02" and ev[0]["source"]["kind"] == "unofficial", ev)
    check("episode: progress counts it", pg.evaluate(f"__reelnest.S.states[{json.dumps(D)}].status") == "WATCHING" and pg.locator(f".check[data-ep='{E1}']").get_attribute("aria-checked") == "true")
    check("episode: row and history show the source", pg.locator(f".ep-row:has([data-ep='{E1}']) .src-tag").count() == 1 and "Unofficial" in pg.locator(".hist").inner_text())
    pg.locator(f".ep-row:has([data-ep='{E1}']) [data-act=menu]").click(); pg.wait_for_timeout(150)
    pg.locator(f"[data-act=watch-ep-new][data-ep='{E1}']").click(); pg.wait_for_timeout(400)
    check("episode: rewatch dialog defaults to rewatch", pg.locator("#wd-re").is_checked() and "Log a rewatch" in pg.locator("#m-title").inner_text())
    pg.locator(".src", has_text="Other platform").click(); pg.locator("#src-other").fill("Netflix (friend's account)")
    pg.locator("[data-act=watch-save]").click(); pg.wait_for_timeout(300)
    ev = active(pg, D)
    check("episode: rewatch with a different source, progress unchanged", len(ev) == 2 and {e["source"]["kind"] for e in ev} == {"unofficial", "other"}
          and pg.evaluate(f"__reelnest.progressOf(__reelnest.S.episodes[{json.dumps(D)}], new Set(Object.values(__reelnest.S.events).filter(e=>e.workId==={json.dumps(D)} && e.deletedAt==null).map(e=>e.episodeId)), '{T.isoformat()}', false).watched") == 1)
    # edit an episode's watch via the menu
    pg.locator(f".ep-row:has([data-ep='{E1}']) [data-act=menu]").click(); pg.wait_for_timeout(150)
    pg.locator(f"[data-act=watch-ep-edit][data-ep='{E1}']").click(); pg.wait_for_timeout(300)
    pg.locator(".src", has_text="Theater").click(); pg.locator("[data-act=watch-save]").click(); pg.wait_for_timeout(300)
    check("episode: latest watch edited to Theater", any(e["source"] and e["source"]["kind"] == "theater" for e in active(pg, D)) and len(active(pg, D)) == 2)
    # older record without source/watchedDate still renders
    pg.evaluate(f"""() => {{ const R = __reelnest; const id = 'old-' + Date.now(); R.S.events[id] = {{ id, workId: {json.dumps(D)}, episodeId: 'tmdb:ep:5002', watchedAt: new Date(2018, 0, 3, 21).getTime(), isRewatch: false, createdAt: Date.now(), deletedAt: null, deviceId: 'old' }}; }}""")
    pg.evaluate("location.hash='#library'"); pg.wait_for_timeout(200); pg.locator(".tile, .row", has_text="Dark").first.click(); pg.wait_for_timeout(700)
    check("old records: no source/date field still shown, with no errors", app_fmt(pg, "2018-01-03") in pg.locator(".hist").inner_text() and not errs, errs)
    pg.locator(".hist").scroll_into_view_if_needed(); pg.screenshot(path="/home/claude/webtest/f4-episode-history.png")
    backup = pg.evaluate("__reelnest.exportJson()")
    ctx.close()

    # ================= 5. Import into another device in another time zone =================
    ctx, pg, errs = new_page(b, tz="America/Los_Angeles")
    pg.evaluate("location.hash='#profile'"); pg.wait_for_timeout(200)
    pg.locator("[data-act=import]").click(); pg.wait_for_timeout(200)
    pg.locator("#imp-text").fill(backup); pg.locator("[data-act=import-check]").click(); pg.wait_for_timeout(300)
    pg.locator("[data-act=import-apply]").click(); pg.wait_for_timeout(500)
    ev = active(pg, "tmdb:series:70523")
    check("import: sources come back", {(e["source"] or {}).get("kind") for e in ev} == {"unofficial", "theater", None}, ev)
    check("time zone: 2 Jan 2018 is still 2 Jan 2018 in Los Angeles", any(pg.evaluate("(e) => __reelnest.evDate(e)", e) == "2018-01-02" for e in ev))
    check("no page errors (import)", not errs, errs); ctx.close()

    # ================= 6. Cloud sync of the new fields =================
    ctx, pg, errs = new_page(b, cloud=True)
    pg.evaluate("location.hash='#profile'"); pg.wait_for_timeout(200)
    pg.locator("#sb-email").fill("ayush@example.com"); pg.locator("[data-act=sb-send]").click(); pg.wait_for_timeout(300)
    pg.locator("details summary:has-text('code instead')").click(); pg.locator("#sb-code").fill("123456"); pg.locator("[data-act=sb-verify]").click(); pg.wait_for_timeout(1200)
    if pg.locator("[data-act=sync-merge-ok]").count(): pg.locator("[data-act=sync-merge-ok]").click(); pg.wait_for_timeout(1200)
    go_discover(pg); open_tile(pg, "3 Idiots"); pg.wait_for_timeout(400)
    pg.locator("[data-act=movie-watch]").click(); pg.wait_for_timeout(300)
    pg.locator("#wd-input").fill("14/02/2015"); pg.keyboard.press("Tab"); pg.locator(".src", has_text="Netflix").click()
    pg.locator("[data-act=watch-save]").click(); pg.wait_for_timeout(300)
    pg.evaluate("__reelnest.Sync.run()"); pg.wait_for_timeout(2500)
    row = psql("select watched_date || '|' || (source->>'kind') || '|' || (source->>'name') from rn_events where work_id = 'tmdb:movie:20453' and deleted_at is null")
    check("cloud: watch date and source stored on the server", row == "2015-02-14|ott|Netflix", row)
    ctx.close()
    ctx2, pg2, errs2 = new_page(b, cloud=True, tz="Europe/London")
    pg2.evaluate("location.hash='#profile'"); pg2.wait_for_timeout(200)
    pg2.locator("#sb-email").fill("ayush@example.com"); pg2.locator("[data-act=sb-send]").click(); pg2.wait_for_timeout(300)
    pg2.locator("details summary:has-text('code instead')").click(); pg2.locator("#sb-code").fill("123456"); pg2.locator("[data-act=sb-verify]").click(); pg2.wait_for_timeout(1500)
    if pg2.locator("[data-act=sync-merge-ok]").count(): pg2.locator("[data-act=sync-merge-ok]").click(); pg2.wait_for_timeout(1500)
    ev = [e for e in active(pg2, "tmdb:movie:20453")]
    check("cloud: second device receives date and source", len(ev) == 1 and ev[0]["watchedDate"] == "2015-02-14" and ev[0]["source"]["name"] == "Netflix", ev)
    check("no page errors (cloud)", not errs and not errs2, (errs, errs2)); ctx2.close()
    b.close()
print(f"\n{sum(ok)}/{len(ok)} passed")
