"""End-to-end tests for the ReelNest web app.

Network is simulated at the browser boundary only:
  * TMDB answers come from small fixtures below (this workspace cannot reach TMDB).
  * The "Supabase" server is the real schema (web/supabase/schema.sql) running in a local
    PostgreSQL 16; auth endpoints are a thin stand-in that issues per-user tokens.
Everything inside the page is the real app code.
"""
import json, subprocess, uuid, io, sys
from urllib.parse import urlparse, parse_qs
from playwright.sync_api import sync_playwright
from PIL import Image

APP = "file:///home/claude/web/index.html"
SB = "https://test.supabase.co"
results = []
def check(name, cond, info=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  :: {info}"))

# ---------------- PostgreSQL-backed fake Supabase ----------------
def psql(sql):
    r = subprocess.run(["psql", "-h", "/tmp", "-p", "5544", "-U", "postgres", "-d", "rn", "-At", "-q", "-v", "ON_ERROR_STOP=1", "-c", sql], capture_output=True, text=True)
    if r.returncode != 0: raise RuntimeError(r.stderr)
    return r.stdout.strip()

def reset_db():
    subprocess.run(["psql", "-h", "/tmp", "-p", "5544", "-U", "postgres", "-q", "-c", "drop database if exists rn", "-c", "create database rn"], capture_output=True)
    for f in ["/home/claude/webtest/sql/shim.sql", "/home/claude/web/supabase/schema.sql"]:
        r = subprocess.run(["psql", "-h", "/tmp", "-p", "5544", "-U", "postgres", "-d", "rn", "-q", "-v", "ON_ERROR_STOP=1", "-f", f], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

NET = {"supabase_down": False, "tmdb_down": False}
def uid_for(email): return str(uuid.uuid5(uuid.NAMESPACE_DNS, email))

def supabase(route):
    req = route.request
    u = urlparse(req.url)
    if NET["supabase_down"]: return route.abort("connectionrefused")
    body = json.loads(req.post_data) if req.post_data else {}
    auth = req.headers.get("authorization", "")
    def ok(obj, status=200): return route.fulfill(status=status, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps(obj))
    if req.method == "OPTIONS": return route.fulfill(status=204, headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "*", "Access-Control-Allow-Methods": "*"})
    if u.path == "/auth/v1/otp": return ok({})
    if u.path == "/auth/v1/verify":
        if body.get("token") != "123456": return ok({"msg": "Token has expired or is invalid"}, 403)
        uid = uid_for(body["email"]); psql(f"insert into auth.users values ('{uid}') on conflict do nothing")
        return ok({"access_token": "tok:" + uid, "refresh_token": "ref:" + uid, "expires_in": 3600, "user": {"id": uid, "email": body["email"]}})
    if u.path == "/auth/v1/token":
        uid = body["refresh_token"].split(":", 1)[1]
        return ok({"access_token": "tok:" + uid, "refresh_token": "ref:" + uid, "expires_in": 3600, "user": {"id": uid}})
    if u.path == "/auth/v1/logout": return route.fulfill(status=204, headers={"Access-Control-Allow-Origin": "*"})
    if u.path.startswith("/rest/v1/rpc/"):
        if not auth.startswith("Bearer tok:"): return ok({"message": "JWT expired"}, 401)
        uid = auth.split("tok:", 1)[1]; fn = u.path.rsplit("/", 1)[1]
        pre = f"set role authenticated; select set_config('request.jwt.claim.sub', '{uid}', false);"
        if fn == "rn_pull": out = psql(pre + f" select rn_pull({int(body['since'])});").splitlines()[-1]; return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=out)
        if fn == "rn_pull_since":
            c = body.get("cursor"); arg = "null" if c is None else "'" + str(c).replace("'", "") + "'"
            return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=psql(pre + f" select rn_pull_since({arg});").splitlines()[-1])
        if fn == "rn_push": psql(pre + " select rn_push($rnj$" + json.dumps(body["payload"]) + "$rnj$::jsonb);"); return ok(1)
        if fn == "rn_delete_my_data": psql(pre + " select rn_delete_my_data();"); return ok(None)
    return ok({"msg": "not found"}, 404)

# ---------------- TMDB fixtures ----------------
buf = io.BytesIO(); Image.new("RGB", (20, 30), (200, 30, 40)).save(buf, "PNG"); PNG = buf.getvalue()
TV = {"id": 61145, "name": "Panchayat", "original_name": "पंचायत", "first_air_date": "2020-04-03", "episode_run_time": [32],
      "genres": [{"id": 35, "name": "Comedy"}], "original_language": "hi", "origin_country": ["IN"], "status": "Returning Series",
      "poster_path": "/p.jpg", "backdrop_path": "/b.jpg", "seasons": [{"season_number": 1, "name": "Season 1", "episode_count": 3, "air_date": "2020-04-03"}],
      "credits": {"cast": [{"name": "Jitendra Kumar"}], "crew": []}, "created_by": [{"name": "Deepak Kumar Mishra"}], "networks": [{"name": "Prime Video"}],
      "alternative_titles": {"results": []}, "content_ratings": {"results": [{"iso_3166_1": "IN", "rating": "U/A 13+"}, {"iso_3166_1": "US", "rating": "TV-14"}]},
      "videos": {"results": []}, "external_ids": {"imdb_id": "tt12004706"}, "vote_average": 8.9, "vote_count": 500, "number_of_seasons": 1, "number_of_episodes": 3}
SEASON = {"episodes": [{"id": 9001, "season_number": 1, "episode_number": 1, "name": "Gram Panchayat Phulera", "air_date": "2020-04-03", "runtime": 32},
                       {"id": 9002, "season_number": 1, "episode_number": 2, "name": "Tanki", "air_date": "2020-04-03", "runtime": 30},
                       {"id": 9003, "season_number": 1, "episode_number": 3, "name": "Biraadri", "air_date": "2020-04-03", "runtime": 31}]}
MOVIE = {"id": 777, "title": "Obscure Film", "original_title": "Obscure Film", "release_date": "2019-01-01", "runtime": 95, "genres": [], "original_language": "ml",
         "production_countries": [{"iso_3166_1": "IN"}], "poster_path": "/m.jpg", "credits": {"cast": [], "crew": []}, "alternative_titles": {"titles": []},
         "release_dates": {"results": []}, "videos": {"results": []}}
PROV_TV = {"results": {"IN": {"link": "https://www.themoviedb.org/tv/61145-panchayat/watch?locale=IN", "flatrate": [{"provider_id": 119, "provider_name": "Amazon Prime Video", "logo_path": "/prime.jpg", "display_priority": 1}]},
                       "US": {"link": "https://www.themoviedb.org/tv/61145-panchayat/watch?locale=US", "buy": [{"provider_id": 2, "provider_name": "Apple TV", "logo_path": "/apple.jpg", "display_priority": 2}]}}}
TRENDING = {"page": 1, "total_pages": 1, "results": [{"id": 61145, "media_type": "tv", "name": "Panchayat", "original_name": "पंचायत", "first_air_date": "2020-04-03", "original_language": "hi", "origin_country": ["IN"], "genre_ids": [35], "poster_path": "/p.jpg"},
                                                    {"id": 777, "media_type": "movie", "title": "Obscure Film", "release_date": "2019-01-01", "original_language": "ml", "genre_ids": [], "poster_path": "/m.jpg"}]}
def tmdb(route):
    u = urlparse(route.request.url); h = u.hostname
    if h in ("image.tmdb.org", "media.themoviedb.org", "wsrv.nl", "images.weserv.nl"):
        return route.fulfill(status=200, content_type="image/png", body=PNG)
    if NET["tmdb_down"]: return route.abort("connectionreset")
    p = u.path.replace("/3/", "/")
    data = (PROV_TV if p.endswith("/tv/61145/watch/providers") else {"results": {}} if p.endswith("/watch/providers")
            else SEASON if "/season/" in p else TV if p.startswith("/tv/") else MOVIE if p.startswith("/movie/")
            else {"page": 1, "total_pages": 1, "results": [r for r in TRENDING["results"] if r["media_type"] == ("movie" if "discover/movie" in p else "tv")]} if "discover/" in p
            else TRENDING if ("trending" in p or "search" in p) else {"genres": []})
    return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps(data))

def new_page(browser, w=1280, h=900, dark=True, cloud=True, key=True):
    ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme="dark" if dark else "light")
    ctx.route("**/*", lambda r: r.abort() if urlparse(r.request.url).hostname == "accounts.google.com" else supabase(r) if urlparse(r.request.url).hostname == "test.supabase.co"
              else tmdb(r) if urlparse(r.request.url).hostname not in (None, "") and "fonts" not in r.request.url else r.continue_())
    pg = ctx.new_page(); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(APP)
    pg.evaluate(f"""() => {{ localStorage.clear(); {"localStorage.setItem('reelnest.tmdbKey','k');" if key else ""}
        {f"localStorage.setItem('reelnest.sbUrl','{SB}'); localStorage.setItem('reelnest.sbKey','anon-public-key-for-tests-0123456789');" if cloud else ""} }}""")
    pg.reload(); pg.wait_for_timeout(300)
    return ctx, pg, errs

def tab(pg, name): pg.locator(f".side [data-id={name}], .tabbar [data-id={name}]").locator("visible=true").first.click(); pg.wait_for_timeout(250)

def visible_card(pg, sel):
    return pg.evaluate("""(sel) => { const el = document.querySelector(sel); if (!el) return false;
      const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + Math.min(r.height / 2, 40));
      return r.width > 100 && r.height > 60 && cs.opacity === '1' && cs.visibility === 'visible' && !!hit && el.contains(hit); }""", sel)

def sign_in(pg, email="ayush@example.com"):
    tab(pg, "profile")
    pg.fill("#sb-email", email); pg.click("[data-act=sb-send]"); pg.wait_for_timeout(300)
    pg.click("details summary:has-text('code instead')")
    pg.fill("#sb-code", "123456"); pg.click("[data-act=sb-verify]"); pg.wait_for_timeout(900)

def add_panchayat(pg):
    tab(pg, "discover"); pg.wait_for_timeout(500)
    pg.fill("#disc-q", "Panchayat"); pg.wait_for_timeout(900)
    pg.locator(".dtile .dtile-open", has_text="Panchayat").first.click(); pg.wait_for_timeout(1200)
    if pg.locator("[data-act=lib-add]").count(): pg.click("[data-act=lib-add]"); pg.wait_for_timeout(200)

reset_db()
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])

    # ===== 1-3: search an Indian series, India availability, region change =====
    ctx, pg, errs = new_page(b, cloud=False)
    add_panchayat(pg)
    check("1 search finds Indian series and opens details", pg.locator("h1", has_text="Panchayat").count() == 1 and pg.locator(".ep-row").count() == 3)
    sec = pg.locator(".card", has_text="Where to watch in India")
    check("2 'Where to watch in India' shows grouped provider with logo", sec.count() == 1 and "subscription" in sec.inner_text().lower() and "Amazon Prime Video" in sec.inner_text() and sec.locator(".prov-logo img").count() == 1, sec.inner_text() if sec.count() else "")
    check("2 attribution, refresh date and title-level label", "JustWatch" in sec.inner_text() and "Last refreshed" in sec.inner_text() and "not individual seasons" in sec.inner_text())
    check("2 link only from provider data", sec.locator("a", has_text="See offers").get_attribute("href") == PROV_TV["results"]["IN"]["link"])
    check("2 certification for India", pg.locator(".pill", has_text="U/A 13+").count() == 1)
    pg.screenshot(path="/home/claude/webtest/s1-detail-india.png", full_page=True)
    # region change
    tab(pg, "profile"); pg.select_option("#region", "US"); pg.wait_for_timeout(300)
    tab(pg, "library"); pg.locator(".grid .tile").first.click(); pg.wait_for_timeout(1200)
    sec = pg.locator(".card", has_text="Where to watch in United States")
    check("3 region change relabels and refetches availability", sec.count() == 1 and "Apple TV" in sec.inner_text() and "buy" in sec.inner_text().lower(), sec.inner_text() if sec.count() else "")
    check("3 certification follows region", pg.locator(".pill", has_text="TV-14").count() == 1 and pg.locator(".pill", has_text="U/A 13+").count() == 0)
    check("3 country of origin stays India", "India" in pg.locator(".facts").inner_text())
    tab(pg, "profile"); pg.select_option("#region", "IN"); pg.wait_for_timeout(200)
    # title with no provider data
    tab(pg, "discover"); pg.fill("#disc-q", "Obscure"); pg.wait_for_timeout(900)
    pg.locator(".dtile .dtile-open", has_text="Obscure Film").first.click(); pg.wait_for_timeout(1200)
    sec = pg.locator(".card", has_text="Where to watch in India")
    check("2 no-data title says 'No providers found' without claiming unavailability", "No providers found" in sec.inner_text() and "doesn't mean it can't be watched" in sec.inner_text())
    # provider error + retry
    NET["tmdb_down"] = True; pg.click("[data-act=watch-refresh]"); pg.wait_for_timeout(1500)
    check("2 network error shown with retry", pg.locator(".card", has_text="Where to watch").get_by_role("button", name="Try again").count() == 1)
    NET["tmdb_down"] = False; pg.get_by_role("button", name="Try again").first.click(); pg.wait_for_timeout(700)
    check("2 retry recovers", pg.get_by_role("button", name="Try again").count() == 0)

    # ===== 4: mark episode; Home card visible; Library progress =====
    tab(pg, "library"); pg.locator(".grid .tile", has_text="Panchayat").first.click(); pg.wait_for_timeout(900)
    pg.locator(".ep-row .check").first.click(); pg.wait_for_timeout(200)
    tab(pg, "home")
    check("4 Continue Watching card is actually visible (desktop)", visible_card(pg, ".next-card"))
    check("4 card shows series, next episode, mark button", "Panchayat" in pg.locator(".next-card").inner_text() and "S01E02" in pg.locator(".next-card").inner_text() and pg.locator(".watch-btn").count() == 1)
    pg.click(".watch-btn"); pg.wait_for_timeout(200)
    check("4 marking advances next episode", "S01E03" in pg.locator(".next-card").inner_text())
    pg.click(".toast button:has-text('Undo')"); pg.wait_for_timeout(200)
    check("4 undo restores", "S01E02" in pg.locator(".next-card").inner_text())
    tab(pg, "library"); check("4 library shows episode progress", "1/3 episodes" in pg.locator(".grid").inner_text())
    # ===== 5: persistence =====
    pg.wait_for_timeout(600); pg.reload(); pg.wait_for_timeout(500); tab(pg, "home")
    check("5 data survives reload", "S01E02" in pg.locator(".next-card").inner_text())
    # ===== 7: offline / error states for search; export/import =====
    NET["tmdb_down"] = True; tab(pg, "discover"); pg.fill("#disc-q", "Jailer"); pg.wait_for_timeout(1000)
    check("7 search error is distinct from no-results", pg.locator("text=Couldn't reach").count() >= 1 and pg.locator("text=No match").count() == 0)
    NET["tmdb_down"] = False
    tab(pg, "profile"); pg.click("[data-act=export]"); data = pg.locator(".sheet textarea").input_value(); pg.click("[data-act=modal-close]")
    exp = json.loads(data)
    check("7 export has library and history", len(exp["works"]) >= 2 and any(e["deletedAt"] is None for e in exp["events"]))
    check("no Android wording in UI", pg.evaluate("document.body.innerText.includes('Android')") is False)
    check("no page errors (part 1)", not errs, errs[:3])
    ctx.close()

    # ===== manual entry + link to catalog =====
    ctx, pg, errs = new_page(b, cloud=False)
    tab(pg, "library"); pg.click("[data-act=manual]"); pg.fill("#mf-title", "Panchayat (my entry)"); pg.fill("#mf-perSeason", "4"); pg.click("[data-act=mf-save]"); pg.wait_for_timeout(400)
    pg.locator(".ep-row .check").nth(0).click(); pg.locator(".ep-row .check").nth(3).click(); pg.wait_for_timeout(150)
    pg.fill("#notes", "watched with family"); pg.locator("h1").click(); pg.wait_for_timeout(200)
    pg.click("[data-act=menu][data-id=detail]"); pg.click("text=Link to catalog entry…"); pg.wait_for_timeout(900)
    pg.locator(".sheet .row", has_text="Panchayat").first.click(); pg.wait_for_timeout(900)
    prev = pg.locator(".sheet").inner_text()
    check("link preview shows matched, moved and kept", "Episodes matched" in prev and "Watch records moved" in prev and "S01E04" in prev, prev)
    pg.click("[data-act=link-apply]"); pg.wait_for_timeout(900)
    st = pg.evaluate("() => { const S = __reelnest.S; const st = S.states['tmdb:series:61145']; const ev = Object.values(S.events).filter(e => e.workId === 'tmdb:series:61145' && e.deletedAt == null).map(e => e.episodeId).sort(); return { notes: st && st.notes, ev, manualLeft: Object.keys(S.states).filter(k => k.startsWith('manual:')).length }; }")
    check("link keeps notes and moves progress (E01→catalog, E04 kept manual)", st["notes"] == "watched with family" and "tmdb:ep:9001" in st["ev"] and len(st["ev"]) == 2 and st["manualLeft"] == 0, st)
    check("no page errors (manual/link)", not errs, errs[:3])
    ctx.close()

    # ===== 6: cloud backup, restore, merge, offline, delete =====
    ctx, pg, errs = new_page(b)
    tab(pg, "profile")
    check("6 local-only status explained before sign-in", pg.locator("text=Clearing browser data").count() == 1)
    add_panchayat(pg); pg.locator(".ep-row .check").first.click(); pg.wait_for_timeout(200)
    pg.click("[data-act=set-rating][data-v='8']"); pg.wait_for_timeout(200)
    sign_in(pg)
    check("6 first sign-in with local data asks to merge (never silent)", pg.locator(".sheet h2", has_text="Combine your libraries").count() == 1)
    pg.click("[data-act=sync-merge-ok]"); pg.wait_for_timeout(2500)
    card = pg.locator(".card", has_text="Cloud backup on").inner_text()
    check("6 backed up only after server confirmed", "Backed up" in card and "Changes waiting to upload\n0" in card.replace("\t", "\n"), card)
    rows = psql("select count(*) from rn_events where deleted_at is null") ; check("6 server has the watch record", rows == "1", rows)
    # offline edit -> pending -> error shown -> retry succeeds
    NET["supabase_down"] = True
    tab(pg, "library"); pg.locator(".grid .tile").first.click(); pg.wait_for_timeout(500)
    pg.locator(".ep-row .check").nth(1).click(); pg.wait_for_timeout(3500)
    tab(pg, "profile"); card = pg.locator(".card", has_text="Cloud backup on").inner_text()
    check("6 offline: change waits and error is visible", "Sync problem" in card and "Retry now" in card, card)
    NET["supabase_down"] = False; pg.click("text=Retry now"); pg.wait_for_timeout(1500)
    check("6 retry uploads pending change", psql("select count(*) from rn_events where deleted_at is null") == "2")

    # second, fresh browser: restore
    ctx2, pg2, errs2 = new_page(b)
    sign_in(pg2)
    pg2.wait_for_timeout(1500); tab(pg2, "library")
    restored = pg2.evaluate("() => { const S = __reelnest.S; const st = S.states['tmdb:series:61145']; return { titles: Object.keys(S.states).length, rating: st && st.rating, watched: Object.values(S.events).filter(e => e.deletedAt == null).length }; }")
    check("6 fresh browser restores library, rating and history", restored == {"titles": 1, "rating": 8, "watched": 2}, restored)
    pg2.locator(".grid .tile").first.click(); pg2.wait_for_timeout(1200)
    check("6 restored series reloads its episodes", pg2.locator(".ep-row").count() == 3)
    # concurrent edits to different fields on two devices
    pg2.click("[data-act=set-watchlist]"); pg2.wait_for_timeout(200)
    pg.click(".side [data-id=library], .tabbar [data-id=library]") if False else None
    tab(pg, "library"); pg.locator(".grid .tile").first.click(); pg.wait_for_timeout(400)
    pg.click("[data-act=set-status][data-v=ON_HOLD]"); pg.wait_for_timeout(200)
    for x in (pg2, pg, pg2):
        x.evaluate("() => __reelnest.Sync.run()"); x.wait_for_timeout(1500)
    a = pg.evaluate("() => { const s = __reelnest.S.states['tmdb:series:61145']; return [s.watchlist, s.status, s.rating]; }")
    c = pg2.evaluate("() => { const s = __reelnest.S.states['tmdb:series:61145']; return [s.watchlist, s.status, s.rating]; }")
    check("6 edits to different fields on two devices both survive", a == c == [True, "ON_HOLD", 8], (a, c))
    # deletion propagates and is not resurrected
    pg.click("[data-act=menu][data-id=detail]"); pg.click("text=Remove from library…"); pg.click("[data-act=modal-ok]"); pg.wait_for_timeout(300)
    pg.evaluate("() => __reelnest.Sync.run()"); pg.wait_for_timeout(1500)
    pg2.evaluate("() => __reelnest.Sync.run()"); pg2.wait_for_timeout(1500)
    pg2.evaluate("() => __reelnest.Sync.run()"); pg2.wait_for_timeout(1200)
    check("6 deletion propagates to the other device and stays deleted", pg2.evaluate("() => Object.keys(__reelnest.S.states).length") == 0 and psql("select count(*) from rn_events where deleted_at is null") == "0")
    # third browser with its own local title merges instead of replacing
    ctx3, pg3, errs3 = new_page(b)
    tab(pg3, "library"); pg3.click("[data-act=manual]"); pg3.fill("#mf-title", "Local Only Film"); pg3.click("[data-act=mf-type][data-v=MOVIE]"); pg3.click("[data-act=mf-save]"); pg3.wait_for_timeout(300)
    sign_in(pg3);
    has_dialog = pg3.locator(".sheet h2", has_text="Combine your libraries").count() == 1
    pg3.click("[data-act=sync-merge-cancel]"); pg3.wait_for_timeout(500)
    check("6 'Not now' keeps local data and uploads nothing", has_dialog and pg3.evaluate("() => Object.keys(__reelnest.S.states).length") == 1 and psql("select count(*) from rn_works where body->>'title' = 'Local Only Film'") == "0")
    # delete cloud copy
    pg2.evaluate("() => __reelnest.Sync.deleteCloud()"); pg2.wait_for_timeout(500)
    check("6 delete cloud copy removes server rows", psql("select count(*) from rn_works") == "0")
    check("no page errors (sync)", not (errs or errs2 or errs3), (errs + errs2 + errs3)[:3])
    pg.screenshot(path="/home/claude/webtest/s2-profile-sync.png", full_page=True)
    for c_ in (ctx, ctx2, ctx3): c_.close()

    # ===== 8: every screen at mobile width, light theme =====
    ctx, pg, errs = new_page(b, w=390, h=844, dark=False, cloud=False)
    add_panchayat(pg); pg.locator(".ep-row .check").first.click(); pg.wait_for_timeout(200)
    pg.screenshot(path="/home/claude/webtest/s3-detail-mobile.png", full_page=True)
    for t in ("home", "discover", "library", "calendar", "profile"):
        tab(pg, t); pg.screenshot(path=f"/home/claude/webtest/s4-{t}-mobile.png", full_page=False)
    tab(pg, "home")
    check("8 mobile: Continue Watching card visible", visible_card(pg, ".next-card"))
    overflow = pg.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
    check("8 mobile: no sideways scrolling", not overflow)
    check("no page errors (mobile)", not errs, errs[:3])
    ctx.close(); b.close()

print(f"\n{sum(1 for r in results if r[1])}/{len(results)} passed")
