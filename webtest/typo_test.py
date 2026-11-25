"""Discover search tolerates misspellings."""
import json
src = open("/home/claude/webtest/e2e.py").read()
exec(src[: src.index("reset_db()\nwith sync_playwright")])

CATALOG = [("movie", 157336, "Interstellar", 2014), ("tv", 61145, "Panchayat", 2020), ("movie", 256040, "Baahubali: The Beginning", 2015),
           ("movie", 278, "The Shawshank Redemption", 1994), ("movie", 117263, "Gangs of Wasseypur - Part 1", 2012), ("tv", 1396, "Breaking Bad", 2008),
           ("movie", 360814, "Dangal", 2016), ("movie", 27205, "Inception", 2010),
           ("movie", 1000001, "Kanta Desu!", 2023), ("movie", 1000002, "Kantara", 2022), ("movie", 1000003, "Drishyam: The Conclusion", 2021), ("movie", 1000004, "Drishyam", 2015),
           ("movie", 1000005, "Interstate", 2007), ("tv", 1000006, "The Family Man", 2019), ("movie", 1000007, "Familiar", 2020)]
def rec(m, i, t, y): return {"id": i, "media_type": m, ("title" if m == "movie" else "name"): t, ("release_date" if m == "movie" else "first_air_date"): f"{y}-01-01",
                             "original_language": "en", "overview": "", "poster_path": None, "genre_ids": [], "vote_average": 7.5, "vote_count": 1000, "popularity": 50}
WIKI = {"interstaller": {"suggestion": "interstellar", "search": []}, "kantaara": {"suggestion": "kantara", "search": []},
        "the familly man": {"suggestion": "the family man", "search": [{"title": "Familialism"}, {"title": "Machismo"}]}, "bahubaali": {"search": [{"title": "Baahubali: The Beginning"}]},
        "panchyat": {"search": [{"title": "Panchayat (TV series)"}]}, "breking bad": {"suggestion": "breaking bad", "search": [{"title": "Breaking Bad"}]}, "inseption": {"suggestion": "inception", "search": [{"title": "Inception"}]}}
wiki_calls = []; wiki_down = {"v": False}
def tmdb2(route):
    u = urlparse(route.request.url)
    if u.hostname == "en.wikipedia.org":
        q = dict(x.split("=", 1) for x in u.query.split("&")).get("srsearch", "")
        from urllib.parse import unquote_plus
        q = unquote_plus(q).lower(); wiki_calls.append(q)
        if wiki_down["v"]: return route.abort("connectionreset")
        w = WIKI.get(q, {"search": []})
        body = {"query": {"searchinfo": ({"suggestion": w["suggestion"]} if "suggestion" in w else {}), "search": w["search"]}}
        return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps(body))
    if "/search/" in u.path:   # like TMDB: words must match (no spelling tolerance); prefix of a word counts
        from urllib.parse import parse_qs
        q = parse_qs(u.query).get("query", [""])[0].lower().replace(":", " ").replace("-", " ").split()
        hits = [rec(*c) for c in CATALOG if all(any(w.startswith(x) for w in c[2].lower().replace(":", " ").replace("-", " ").split()) for x in q)]
        return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps({"page": 1, "total_pages": 1, "results": hits}))
    return tmdb(route)

def search(pg, text):
    pg.fill("#disc-q", text); pg.wait_for_timeout(1300)
    return [t for t in pg.locator(".dtile .dtile-meta .t").all_inner_texts()]

reset_db()
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx, pg, errs = new_page(b)
    ctx.unroute("**/*")
    ctx.route("**/*", lambda r: r.abort() if urlparse(r.request.url).hostname == "accounts.google.com" else supabase(r) if urlparse(r.request.url).hostname == "test.supabase.co"
              else tmdb2(r) if urlparse(r.request.url).hostname not in (None, "") and "fonts" not in r.request.url else r.continue_())
    pg.reload(); pg.wait_for_timeout(400); tab(pg, "discover")
    res = search(pg, "Interstellar")
    check("T1 a correct spelling works as before and doesn't ask Wikipedia", res[:1] == ["Interstellar"] and not wiki_calls, (res, wiki_calls))
    for typed, want in [("interstaller", "Interstellar"), ("bahubaali", "Baahubali: The Beginning"), ("panchyat", "Panchayat"), ("breking bad", "Breaking Bad"),
                        ("shawshank redemtion", "The Shawshank Redemption"), ("gangs of waseepur", "Gangs of Wasseypur - Part 1")]:
        res = search(pg, typed)
        note = pg.locator("text=Showing results for").count()
        check(f"T2 '{typed}' finds {want} first", res[:1] == [want], res[:4])
        check(f"T2 ...and says what it searched for", note == 1)
    res = search(pg, "the familly man")
    check("T10 'the familly man' finds The Family Man", res[:1] == ["The Family Man"], res)
    res = search(pg, "interstaller")
    check("T11 a real correction beats an equally close lookalike (Interstellar, not Interstate)", res[:1] == ["Interstellar"], res)
    res = search(pg, "kantaara")
    check("T8 doubled letters are forgiven even when Wikipedia has nothing (kantaara -> Kantara)", res[:1] == ["Kantara"], res)
    check("T8 ...and it says it corrected the spelling", pg.locator("text=Showing results for").count() == 1)
    res = search(pg, "drisyam")
    check("T9 an equally close shorter title comes first (Drishyam before Drishyam: The Conclusion)", res[:2] == ["Drishyam", "Drishyam: The Conclusion"], res)
    res = search(pg, "panchyat")
    pg.locator("[data-act=disc-exact]").click(); pg.wait_for_timeout(1200)
    check("T3 'Search only for' shows the exact-spelling results", pg.locator("text=Showing results for").count() == 0 and "Panchayat" not in pg.locator(".dtile .dtile-meta .t").all_inner_texts())
    wiki_down["v"] = True
    res = search(pg, "interstel")
    check("T4 typing part of a title still works with Wikipedia unreachable", res[:1] == ["Interstellar"], res)
    res = search(pg, "breking")
    check("T4 a one-word typo still works with Wikipedia unreachable (shorter search)", res[:1] == ["Breaking Bad"], res)
    wiki_down["v"] = False
    res = search(pg, "zzqxv")
    check("T5 nonsense finds nothing and doesn't invent a match", not res and pg.locator("text=Showing results for").count() == 0, res)
    res = search(pg, "inseption")
    check("T6 doesn't confuse Inception with Interstellar", res[:1] == ["Inception"], res)
    check("T7 only the typed words go to Wikipedia", all(c in ("interstaller", "bahubaali", "panchyat", "breking bad", "shawshank redemtion", "gangs of waseepur", "zzqxv", "inseption", "interstel", "breking", "kantaara", "drisyam", "the familly man") for c in wiki_calls), wiki_calls)
    check("no page errors", not errs, errs[:3])
    b.close()
print(f"\n{sum(1 for r in results if r[1])}/{len(results)} passed")
