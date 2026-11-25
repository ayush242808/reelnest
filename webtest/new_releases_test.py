"""Discover: New releases row."""
import json, datetime
from urllib.parse import parse_qs
src = open('/home/claude/webtest/disc_home.py').read()
exec(src.split("with sync_playwright() as p:")[0])
def tab(pg, name): pg.locator(f".side [data-id={name}], .tabbar [data-id={name}]").locator("visible=true").first.click(); pg.wait_for_timeout(250)

TODAY = datetime.date.today()
def mk(kind, i, title, days_old, votes=12, avg=6.1, lang="en"):
    d = (TODAY - datetime.timedelta(days=days_old)).isoformat()
    r = {"id": 900000 + i, ("title" if kind == "movie" else "name"): title, ("release_date" if kind == "movie" else "first_air_date"): d,
         "original_language": lang, "overview": "", "poster_path": f"/p{i}.jpg", "genre_ids": [], "vote_average": avg, "vote_count": votes, "popularity": 100 - i}
    return r
NEW_M = [mk("movie", i, f"New Film {i}", 5 + i) for i in range(4)]
NEW_T = [mk("tv", 10 + i, f"New Show {i}", 8 + i) for i in range(3)]
NEW_IN = [mk("movie", 20 + i, f"New Indian Film {i}", 10 + i, lang="hi") for i in range(3)]
asked = []
def tm2(route):
    u = urlparse(route.request.url); qs = {k: v[0] for k, v in parse_qs(u.query).items()}
    is_new = ("primary_release_date.gte" in qs and qs.get("vote_count.gte", "0") in ("10", "0") and qs["primary_release_date.gte"] > (TODAY - datetime.timedelta(days=100)).isoformat()) \
             or ("first_air_date.gte" in qs and qs["first_air_date.gte"] > (TODAY - datetime.timedelta(days=100)).isoformat())
    if is_new:
        asked.append((u.path, qs))
        res = NEW_T if "discover/tv" in u.path else NEW_IN if qs.get("with_origin_country") == "IN" else NEW_M
        return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps({"page": 1, "total_pages": 1, "results": res}))
    return tm(route)
def router(r):
    h = urlparse(r.request.url).hostname
    if h == "accounts.google.com": return r.abort()
    if h and h.endswith("supabase.co"): return r.abort()
    if h not in (None, "") and "fonts" not in r.request.url: return tm2(r)
    return r.continue_()

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 1280, "height": 900}); ctx.route("**/*", router)
    pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto(APP); pg.evaluate("() => { localStorage.clear(); localStorage.setItem('reelnest.tmdbKey','k'); }"); pg.reload(); pg.wait_for_timeout(300)
    go_discover(pg, search=False); pg.wait_for_timeout(900)
    heads = pg.locator(".drow-sec h2").all_inner_texts()
    check("N1 New releases is the first row", heads[:1] == ["New releases"], heads)
    order = pg.evaluate("() => [...document.querySelectorAll('main .drow-sec, main .chips[aria-label^=Verdicts]')].map(e => e.matches('.chips') ? 'verdict-filter' : e.querySelector('h2').innerText)")
    check("N1 ...above the Perfection / Go for It filter (which doesn't apply to it)", order[:2] == ["New releases", "verdict-filter"], order)
    names = pg.locator(".drow-sec", has_text="New releases").locator(".dtile-meta .t").all_inner_texts()
    check("N2 movies, series and Indian movies take turns", names[:6] == ["New Film 0", "New Show 0", "New Indian Film 0", "New Film 1", "New Show 1", "New Indian Film 1"], names)
    check("N3 brand-new titles with few votes are not filtered out by verdict", len(names) == 10, len(names))
    windows = [(p_, q.get("primary_release_date.gte") or q.get("first_air_date.gte"), q.get("primary_release_date.lte") or q.get("first_air_date.lte")) for p_, q in asked]
    check("N4 asks only for releases from the last ~2 months up to today (nothing upcoming)", len(windows) == 3 and all(lo >= (TODAY - datetime.timedelta(days=76)).isoformat() and hi == TODAY.isoformat() for _, lo, hi in windows), windows)
    k = f"tmdb:movie:{NEW_M[0]['id']}"
    pg.evaluate("""(k) => { const S = __reelnest.S; S.works[k] = { id: k, type: 'MOVIE', title: 'New Film 0', providerId: k.split(':').pop() };
        __reelnest.ensureState(k); __reelnest.addWatch(k, null, '2026-11-20', false, null); }""", k)
    tab(pg, "home"); tab(pg, "discover"); pg.wait_for_timeout(400)
    names2 = pg.locator(".drow-sec", has_text="New releases").locator(".dtile-meta .t").all_inner_texts()
    check("N5 a new release you've watched disappears from the row", "New Film 0" not in names2 and len(names2) == 9, names2)
    pg.locator(".drow-sec", has_text="New releases").locator("[data-act=disc-see]").click(); pg.wait_for_timeout(900)
    grid = pg.locator(".dgrid .dtile-meta .t").all_inner_texts()
    check("N6 See all lists them in the same order", grid[:3] == ["New Show 0", "New Indian Film 0", "New Film 1"], grid[:5])
    check("no page errors", not errs, errs[:3])
    b.close()
print(f"\n{sum(ok)}/{len(ok)} passed")
