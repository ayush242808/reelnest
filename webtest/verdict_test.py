"""Discover verdicts from public audience ratings (IMDb via the ratings function + TMDB)."""
import json
src = open('/home/claude/webtest/disc_home.py').read()
exec(src.split("with sync_playwright() as p:")[0])
_e2e = open('/home/claude/webtest/e2e.py').read(); exec(_e2e[: _e2e.index("reset_db()\nwith sync_playwright")])  # its Supabase mock has full auth
def tab(pg, name): pg.locator(f".side [data-id={name}], .tabbar [data-id={name}]").locator("visible=true").first.click(); pg.wait_for_timeout(250)
exec('def sign_in(pg, email="ayush@example.com"):\n    tab(pg, "profile")\n    pg.fill("#sb-email", email); pg.click("[data-act=sb-send]"); pg.wait_for_timeout(300)\n    pg.click("details summary:has-text(\'code instead\')")\n    pg.fill("#sb-code", "123456"); pg.click("[data-act=sb-verify]"); pg.wait_for_timeout(900)\n\n')

# Audience numbers for the "World Movie i" fixtures: (TMDB avg, TMDB votes, IMDb rating, IMDb votes)
NUMS = [(6.6, 900, 6.5, 40000), (8.6, 4000, 8.9, 900000), (7.3, 1200, 7.4, 60000), (5.4, 800, 5.2, 30000), (7.9, 2500, 8.1, 300000), (7.0, 700, 7.0, 15000)]
for i, r in enumerate(MOVIES["results"]): r.update(vote_average=NUMS[i][0], vote_count=NUMS[i][1])
for r in OLD_MOVIES["results"]: r.update(vote_average=6.0, vote_count=50)
IMDB = {f"tmdb:movie:{MOVIES['results'][i]['id']}": {"r": n[2], "v": n[3], "id": f"tt00000{i}"} for i, n in enumerate(NUMS)}
def bay(R, v, m): return (v * R + m * 6.4) / (v + m)
def score(i, with_imdb=True):
    t = NUMS[i]; parts = [(bay(t[0], t[1], 250), 1)] + ([(bay(t[2], t[3], 2500), 3)] if with_imdb else [])
    return round(sum(a * w for a, w in parts) / sum(w for _, w in parts), 1)
def band(s): return "Perfection" if s >= 8 else "Go for It" if s >= 7 else "Time Pass" if s >= 6 else "Skip"

calls = []; fn_state = {"down": False}
def sb(route):
    u = urlparse(route.request.url)
    if u.path == "/functions/v1/ratings":
        if route.request.method == "OPTIONS": return route.fulfill(status=204, headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "authorization, content-type, apikey", "Access-Control-Allow-Methods": "POST, OPTIONS"})
        calls.append(json.loads(route.request.post_data)["keys"])
        if fn_state["down"]: return route.fulfill(status=502, headers={"Access-Control-Allow-Origin": "*"}, body="{}")
        if "Bearer tok:" not in (route.request.headers.get("authorization") or ""): return route.fulfill(status=401, headers={"Access-Control-Allow-Origin": "*"}, body="{}")
        keys = calls[-1]
        return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps({"ratings": {k: IMDB.get(k) for k in keys}, "pending": 0}))
    return supabase(route)
def router(r):
    h = urlparse(r.request.url).hostname
    if h and h.endswith("supabase.co") and h != "test.supabase.co": return r.abort()  # never the real project
    if h == "accounts.google.com": return r.abort()
    if h == "test.supabase.co": return sb(r)
    if h not in (None, "") and "fonts" not in r.request.url: return tm(r)
    return r.continue_()
def row(pg, name): return pg.locator(".drow-sec", has_text=name).locator(".dtile-meta .t").all_inner_texts()
def chips(pg, name): return pg.locator(".drow-sec", has_text=name).locator(".dtile-meta .verdict").all_inner_texts()

reset_db()
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900}, color_scheme="dark"); ctx.route("**/*", router)
    pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(APP); pg.evaluate("() => { localStorage.clear(); localStorage.setItem('reelnest.tmdbKey','k'); localStorage.setItem('reelnest.sbUrl','https://test.supabase.co'); localStorage.setItem('reelnest.sbKey','anon-public-key-for-tests-0123456789'); }"); pg.reload(); pg.wait_for_timeout(300)
    # signed out first: TMDB-only verdicts, no calls to the ratings function
    go_discover(pg, search=False); pg.wait_for_timeout(800)
    exp_out = [f"World Movie {i}" for i in sorted(range(6), key=lambda i: -score(i, False)) if band(score(i, False)) in ("Perfection", "Go for It")]
    got = [t for t in row(pg, "Best movies right now") if t.startswith("World")]
    check("V1 signed out: ranked on TMDB votes alone, no IMDb requests", got == exp_out and not calls, (got, exp_out, len(calls)))
    # signed in
    sign_in(pg); pg.wait_for_timeout(300); tab(pg, "home"); tab(pg, "discover"); pg.wait_for_timeout(1200)
    exp = sorted(range(6), key=lambda i: -score(i))
    keep = [i for i in exp if band(score(i)) in ("Perfection", "Go for It")]
    got = [t for t in row(pg, "Best movies right now") if t.startswith("World")]
    check("V2 signed in: only Go for It and Perfection, best first", got == [f"World Movie {i}" for i in keep], (got, [(i, score(i), band(score(i))) for i in exp]))
    ch = chips(pg, "Best movies right now")
    ch = [" ".join(c.split()) for c in ch]
    check("V3 every tile shows its verdict and score", len(ch) >= len(keep) and ch[0] == f"{band(score(keep[0]))} {score(keep[0]):.1f}", ch[:3])
    check("V4 thinly-rated titles (old tier, 50 votes) are not passed off as great", not any(t.startswith("Great") for t in row(pg, "Best movies right now")))
    check("V5 anime keeps TMDB's order", row(pg, "Popular anime") == [f"Anime Show {i}" for i in range(7)])
    n = len(calls)
    check("V6 ratings come in one batched request", n == 1 and len(calls[0]) <= 60, [len(c) for c in calls])
    pg.reload(); pg.wait_for_timeout(1000); tab(pg, "discover"); pg.wait_for_timeout(800)
    check("V7 cached: a reload makes no new ratings request", len(calls) == n, len(calls))
    pg.click("[data-act=disc-timepass]"); pg.wait_for_timeout(300)
    tp = [i for i in exp if band(score(i)) in ("Perfection", "Go for It", "Time Pass")]
    got = [t for t in row(pg, "Best movies right now") if t.startswith("World")]
    check("V8 'Include Time Pass' adds Time Pass titles in score order", got == [f"World Movie {i}" for i in tp] and len(tp) > len(keep), (got, tp))
    pg.reload(); pg.wait_for_timeout(800); tab(pg, "discover"); pg.wait_for_timeout(500)
    check("V8 ...and is remembered", pg.locator("[data-act=disc-timepass]").get_attribute("aria-pressed") == "true")
    pg.click("[data-act=disc-timepass]"); pg.wait_for_timeout(200)
    # detail page
    best = keep[0]
    pg.locator(".drow-sec", has_text="Best movies right now").locator(".dtile-open", has_text=f"World Movie {best}").first.click(); pg.wait_for_timeout(1500)
    imdb = pg.locator(".ratings-line a.score")
    href = imdb.get_attribute("href") if imdb.count() else None
    mo = pg.locator(".ratings-line a", has_text="Moctale")
    check("V9 title page shows the IMDb rating linking to IMDb", href == f"https://www.imdb.com/title/tt00000{best}/" and f"IMDb {NUMS[best][2]:.1f}" in imdb.inner_text(), href)
    check("V9 ...its verdict, and a Moctale link", pg.locator(".ratings-line .verdict").count() == 1 and mo.count() == 1 and mo.get_attribute("href").startswith("https://www.google.com/search?q=site%3Amoctale.in"), mo.get_attribute("href") if mo.count() else None)
    # function down: Discover still works
    fn_state["down"] = True
    pg.evaluate("() => { localStorage.removeItem('reelnest.ratings'); location.reload(); }"); pg.wait_for_timeout(1200); tab(pg, "discover"); pg.wait_for_timeout(1200)
    check("V10 if ratings are unavailable, rows still show (unranked) instead of going empty", len([t for t in row(pg, "Best movies right now") if t.startswith("World")]) == 6)
    check("no page errors", not errs, errs[:3])
    b.close()
print(f"\n{sum(1 for r in results if r[1])}/{len(results)} passed")
