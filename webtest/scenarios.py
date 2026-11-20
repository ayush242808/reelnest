"""TMDB-key privacy, episode-loading states and sync scenarios 1-10.
Reuses the e2e harness (fake Supabase backed by local PostgreSQL running the real schema)."""
import json, time, threading
src = open("/home/claude/webtest/e2e.py").read()
exec(src[: src.index("reset_db()\nwith sync_playwright")])

KEY = "disposable-test-key-not-real-000"   # fake value; never a real credential
PID = "tmdb:series:61145"
NET.update(hold_seasons=False); HELD = []
_orig_tmdb = tmdb
def tmdb(route):  # noqa: F811  (wraps the e2e fixture: season requests can be held open or failed)
    if "/season/" in route.request.url:
        if NET["tmdb_down"]: return route.abort("connectionreset")
        if NET["hold_seasons"]: HELD.append(route); return
    return _orig_tmdb(route)
def release():
    NET["hold_seasons"] = False
    while HELD: _orig_tmdb(HELD.pop(0))

def run(pg, n=1):
    for _ in range(n): pg.evaluate("() => __reelnest.Sync.run()"); pg.wait_for_timeout(1300)
def server_catalog(email="ayush@example.com"):
    out = psql(f"select coalesce(body->'catalog','null'::jsonb)::text from rn_settings where user_id='{uid_for(email)}'")
    return json.loads(out) if out else None
def ev(pg, js): return pg.evaluate(js)

reset_db()
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])

    # ================= TMDB key: local-only unless opted in =================
    ctx, pg, errs = new_page(b, key=False)
    sign_in(pg); tab(pg, "profile")
    check("K1 sync toggle is shown and OFF by default for a new key", pg.locator("#tmdb-sync").count() == 1 and not pg.is_checked("#tmdb-sync"))
    pg.fill("#tmdb-key", KEY); pg.click("[data-act=save-catalog]"); pg.wait_for_timeout(200); run(pg, 2)
    c = server_catalog()
    check("K2 saving a key with syncing off uploads no key", c is not None and c.get("sync") is False and "key" not in c and KEY not in json.dumps(c), c)
    check("K2 privacy text says the key is not in the cloud", "(currently off)" in pg.inner_text("main"))
    pg.check("#tmdb-sync"); pg.click("[data-act=save-catalog]"); pg.wait_for_timeout(200); run(pg, 2)
    c = server_catalog()
    check("K3 opting in stores the key in the private account row", c and c.get("sync") is True and c.get("key") == KEY, {k: (v if k != "key" else "<present>") for k, v in (c or {}).items()})
    ctxB, pgB, errsB = new_page(b, key=False)
    sign_in(pgB); pgB.wait_for_timeout(500); run(pgB)
    check("K4 a second signed-in device receives the key when opted in", ev(pgB, "() => localStorage.getItem('reelnest.tmdbKey')") == KEY and ev(pgB, "() => localStorage.getItem('reelnest.tmdbSync')") == "on")
    tab(pgB, "profile"); pgB.uncheck("#tmdb-sync"); pgB.click("[data-act=save-catalog]"); pgB.wait_for_timeout(200); run(pgB, 2)
    c = server_catalog()
    check("K5 turning syncing off removes the key from the cloud", c and c.get("sync") is False and "key" not in c and KEY not in psql("select body::text from rn_settings"), c)
    run(pg, 2)
    check("K5 other device learns syncing is off but keeps its own key", ev(pg, "() => [localStorage.getItem('reelnest.tmdbSync'), localStorage.getItem('reelnest.tmdbKey')]") == ["off", KEY])
    exp = ev(pg, "() => __reelnest.exportJson()")
    check("K6 backup export never contains the key", KEY not in exp)
    # Legacy copy uploaded by an earlier version: disclosed, and removable
    psql(f"update rn_settings set body = jsonb_set(body, '{{catalog}}', jsonb_build_object('key','{KEY}','relay','','at', 9999999999999)) where user_id='{uid_for('ayush@example.com')}'")
    ctxC, pgC, errsC = new_page(b, key=False)
    sign_in(pgC); pgC.wait_for_timeout(400); run(pgC); tab(pgC, "profile")
    legacy_banner = pgC.locator(".banner", has_text="set up by an earlier version").count() == 1
    check("K7 a key uploaded by an earlier version is disclosed with a removal path", legacy_banner and pgC.is_checked("#tmdb-sync"))
    pgC.uncheck("#tmdb-sync"); pgC.click("[data-act=save-catalog]"); pgC.wait_for_timeout(200)
    # the legacy record carried a far-future timestamp; the removal must still win
    pgC.evaluate("() => localStorage.setItem('reelnest.tmdbAt', String(9999999999999 + 1))"); pgC.evaluate("() => __reelnest.Sync.markMeta()"); run(pgC, 2)
    check("K7 removing the legacy copy deletes the key from the cloud", KEY not in psql("select body::text from rn_settings"))
    # signed-out save, then sign in: nothing uploaded
    ctxD, pgD, errsD = new_page(b, key=False); tab(pgD, "profile")
    pgD.fill("#tmdb-key", KEY + "-d"); pgD.click("[data-act=save-catalog]"); pgD.wait_for_timeout(200)
    sign_in(pgD, "other@example.com"); pgD.wait_for_timeout(400); run(pgD, 2)
    check("K8 a key saved while signed out is not uploaded at sign-in", (KEY + "-d") not in psql("select coalesce(string_agg(body::text, ''), '') from rn_settings"))
    check("no page errors (key)", not (errs or errsB or errsC or errsD), (errs + errsB + errsC + errsD)[:3])
    for c_ in (ctx, ctxB, ctxC, ctxD): c_.close()

    # ================= Episode progress loading states =================
    reset_db()
    ctx, pg, errs = new_page(b)
    sign_in(pg); add_panchayat(pg); pg.locator(".ep-row .check").first.click(); pg.wait_for_timeout(200); run(pg, 2)
    NET["hold_seasons"] = True
    ctx2, pg2, errs2 = new_page(b); sign_in(pg2); pg2.wait_for_timeout(400); run(pg2)
    pg2.evaluate(f"() => {{ __reelnest.S.episodes['{PID}'] = []; for (const s of __reelnest.S.seasons['{PID}'] || []) s.fetchedAt = null; }}")
    pg2.evaluate(f"() => __reelnest.UI && null"); tab(pg2, "library"); pg2.locator(".grid .tile").first.click(); pg2.wait_for_timeout(900)
    txt = pg2.inner_text("main")
    check("E1 while episodes load: 'Loading episode data' shown, not '0 of 0'", "Loading episode data" in txt and "0 of 0" not in txt and "of 0 aired" not in txt, txt[:300])
    check("E1 watched count is reassured during loading", "1 watched episode is saved" in txt)
    release(); pg2.wait_for_timeout(800)
    txt = pg2.inner_text("main")
    check("E2 after loading, real progress appears (1 of 3)", "1 of 3 aired watched" in txt.replace("\n", " "), txt[:300])
    NET["tmdb_down"] = True
    pg2.evaluate(f"() => {{ __reelnest.S.episodes['{PID}'] = []; for (const s of __reelnest.S.seasons['{PID}'] || []) s.fetchedAt = null; delete __reelnest.EpLoad['{PID}']; }}")
    pg2.click("[data-act=back]") if pg2.locator("[data-act=back]").count() else None
    tab(pg2, "library"); pg2.locator(".grid .tile").first.click(); pg2.wait_for_timeout(1500)
    txt = pg2.inner_text("main")
    check("E3 on failure: 'Couldn't load episode data' with Retry, no zeros", "Couldn't load episode data" in txt and pg2.locator("[data-act=eps-retry]").count() >= 1 and "0 of 0" not in txt, txt[:300])
    check("E3 failure never removed the watch record", ev(pg2, f"() => Object.values(__reelnest.S.events).filter(e => e.workId === '{PID}' && e.deletedAt == null).length") == 1)
    NET["tmdb_down"] = False
    pg2.locator("[data-act=eps-retry]").first.click(); pg2.wait_for_timeout(1500)
    check("E4 Retry recovers and shows progress", "1 of 3 aired watched" in pg2.inner_text("main").replace("\n", " "))
    NET["tmdb_down"] = True
    pg2.evaluate(f"() => {{ __reelnest.S.episodes['{PID}'] = []; for (const s of __reelnest.S.seasons['{PID}'] || []) s.fetchedAt = null; delete __reelnest.EpLoad['{PID}']; }}")
    tab(pg2, "library"); pg2.locator(".grid .tile").first.click(); pg2.wait_for_timeout(1500)
    NET["tmdb_down"] = False
    pg2.evaluate("() => window.dispatchEvent(new Event('online'))"); pg2.wait_for_timeout(1500)
    check("E5 coming back online reloads automatically", "1 of 3 aired watched" in pg2.inner_text("main").replace("\n", " "))
    pg2.reload(); pg2.wait_for_timeout(600); NET["tmdb_down"] = True
    tab(pg2, "library"); pg2.locator(".grid .tile").first.click(); pg2.wait_for_timeout(1200); NET["tmdb_down"] = False
    check("E6 cached episodes show offline after reload", "1 of 3 aired watched" in pg2.inner_text("main").replace("\n", " "))
    check("no page errors (episodes)", not (errs or errs2), (errs + errs2)[:3])
    ctx.close(); ctx2.close()

    # ================= Sync scenarios =================
    reset_db()
    A_ctx, A, eA = new_page(b); sign_in(A)
    B_ctx, B, eB = new_page(b); sign_in(B)
    add_panchayat(A); run(A); run(B)
    # 1 equal timestamps on the same field: deterministic, both converge
    A.evaluate(f"() => {{ const s = __reelnest.S.states['{PID}']; s.notes = 'from A'; s.notesAt = 1800000000000; __reelnest.Persist.touch('{PID}'); }}")
    B.evaluate(f"() => {{ const s = __reelnest.S.states['{PID}']; s.notes = 'from B'; s.notesAt = 1800000000000; __reelnest.Persist.touch('{PID}'); }}")
    run(A); run(B); run(A); run(B)
    na = ev(A, f"() => __reelnest.S.states['{PID}'].notes"); nb = ev(B, f"() => __reelnest.S.states['{PID}'].notes")
    check("S1 equal timestamps resolve the same way on both devices", na == nb and na in ("from A", "from B"), (na, nb))
    # 2 clock skew: a device a year ahead cannot pin its value forever
    A.evaluate(f"() => {{ const s = __reelnest.S.states['{PID}']; s.rating = 3; s.ratingAt = Date.now() + 365*864e5; __reelnest.Persist.touch('{PID}'); }}"); run(A)
    ra = int(psql("select rating_at from rn_states"))
    check("S2 a far-ahead device clock is clamped by the server", ra <= int(time.time()*1000) + 300000 + 5000, ra)
    run(B); run(A)
    check("S2 skewed device adopts the server-clamped timestamp", ev(A, f"() => __reelnest.S.states['{PID}'].ratingAt") == ra)
    # 3 different fields edited on two devices: both survive
    A.evaluate(f"() => __reelnest.setField('{PID}', 'watchlist', true)"); B.evaluate(f"() => __reelnest.setField('{PID}', 'status', 'ON_HOLD')")
    run(A); run(B); run(A)
    check("S3 edits to different fields both survive", ev(A, f"() => [__reelnest.S.states['{PID}'].watchlist, __reelnest.S.states['{PID}'].status]") == ev(B, f"() => [__reelnest.S.states['{PID}'].watchlist, __reelnest.S.states['{PID}'].status]") == [True, "ON_HOLD"])
    # 4 watching the same episode on both devices: two history records, counted once
    A.evaluate(f"() => __reelnest.markEpisodes('{PID}', ['tmdb:ep:9002'])"); B.evaluate(f"() => __reelnest.markEpisodes('{PID}', ['tmdb:ep:9002'])")
    run(A); run(B); run(A)
    check("S4 same episode on two devices: both records kept, counted once", psql(f"select count(*) from rn_events where episode_id='tmdb:ep:9002' and deleted_at is null") == "2"
          and ev(A, f"() => __reelnest.progressOf(__reelnest.S.episodes['{PID}'], new Set(Object.values(__reelnest.S.events).filter(e=>e.workId==='{PID}'&&e.deletedAt==null).map(e=>e.episodeId)), '2099-01-01', false).watched") == 1)
    # 5 network failure mid-sync: nothing lost, retried later, no duplicates
    A.evaluate(f"() => __reelnest.addWatch('{PID}', 'tmdb:ep:9003', '2026-11-01', false, {{kind:'ott', name:'Amazon Prime Video'}})")
    NET["supabase_down"] = True; run(A); NET["supabase_down"] = False
    pending = ev(A, "() => __reelnest.Sync.pending()")
    run(A); run(A)
    check("S5 a failed push keeps the change queued, then uploads once", pending >= 1 and ev(A, "() => __reelnest.Sync.pending()") == 0 and psql("select count(*) from rn_events where episode_id='tmdb:ep:9003'") == "1")
    # 6 duplicate/retried push of identical data changes nothing
    before = psql("select md5(string_agg(id||coalesce(deleted_at::text,''), ',' order by id)) from rn_events")
    A.evaluate("() => { __reelnest.Sync.markAll(); }"); run(A); run(A)
    check("S6 re-pushing everything is idempotent", psql("select md5(string_agg(id||coalesce(deleted_at::text,''), ',' order by id)) from rn_events") == before)
    # 7 stale offline edit vs deletion: later action wins on both devices, deterministically
    run(B)
    NET_B_off = True
    B.route("**/test.supabase.co/**", lambda r: r.abort("connectionrefused"))
    B.evaluate(f"() => __reelnest.setField('{PID}', 'rating', 9)")   # B edits while offline (earlier)
    A.wait_for_timeout(50); A.evaluate(f"() => __reelnest.removeFromLibrary('{PID}')"); run(A)  # A deletes later
    B.unroute("**/test.supabase.co/**"); run(B); run(A); run(B)
    check("S7 deletion after a stale offline edit wins on both devices", ev(A, f"() => !!__reelnest.S.states['{PID}']") is False and ev(B, f"() => !!__reelnest.S.states['{PID}']") is False)
    # 8 edit after deletion keeps the title (and both agree)
    B.evaluate(f"() => __reelnest.setField('{PID}', 'notes', 'came back to it')"); run(B); run(A); run(B)
    check("S8 an edit made after a deletion keeps the title on both devices", ev(A, f"() => __reelnest.S.states['{PID}']?.notes") == ev(B, f"() => __reelnest.S.states['{PID}']?.notes") == "came back to it")
    # 9 fresh device restore: sources, dates, ratings, notes, manual titles, settings
    B.evaluate(f"() => {{ __reelnest.setField('{PID}', 'rating', 8); __reelnest.addWatch('{PID}', 'tmdb:ep:9001', '2025-03-04', true, {{kind:'theater'}}); }}")
    mid = B.evaluate("() => __reelnest.createManual({title:'Home Video', type:'MOVIE', isAnime:false, year:'1999', runtime:'', lang:'', country:'', release:'', originalTitle:'', overview:'', seasons:'1', perSeason:''})")
    B.evaluate("() => { const s = __reelnest.S; s.settings.hideSpoilers = true; s.settingsAt = Date.now(); __reelnest.Persist.touchMeta(); }")
    run(B, 2)
    F_ctx, F, eF = new_page(b, key=False); sign_in(F); F.wait_for_timeout(500); run(F)
    snap = """() => { const S = __reelnest.S, id = 'tmdb:series:61145';
      const evs = Object.values(S.events).filter(e => e.deletedAt == null).map(e => [e.episodeId, e.watchedDate, e.isRewatch, e.source && e.source.kind]).sort();
      return { rating: S.states[id]?.rating, notes: S.states[id]?.notes, evs, manual: Object.values(S.works).filter(w => w.isManual).map(w => w.title), spoil: S.settings.hideSpoilers }; }"""
    sb, sf = ev(B, snap), ev(F, snap)
    check("S9 a fresh device restores ratings, notes, dates, sources, manual titles, settings", sb == sf and sf["rating"] == 8 and ["tmdb:ep:9001", "2025-03-04", True, "theater"] in sf["evs"] and sf["manual"] == ["Home Video"] and sf["spoil"] is True, (sb, sf))
    # 10 backup export -> import on a device with no account
    blob = ev(B, "() => __reelnest.exportJson()")
    G_ctx, G, eG = new_page(b, cloud=False, key=False)
    G.evaluate("(t) => { const r = __reelnest.parseBackup(t); const pl = __reelnest.planImport(r.bundle); window.__plan = pl; }", blob)
    ok_plan = ev(G, "() => !!window.__plan")
    tab(G, "profile"); has_import = G.locator("[data-act=import]").count() >= 1 or G.locator("text=Import").count() >= 1
    G.evaluate("(t) => { const r = __reelnest.parseBackup(t); __reelnest.UI.modal = null; window.__applyImport && window.__applyImport(r); }", blob)
    check("S10 a backup parses and plans an import with no account", ok_plan and has_import)
    check("no page errors (sync scenarios)", not (eA or eB or eF or eG), (eA + eB + eF + eG)[:3])
    for c_ in (A_ctx, B_ctx, F_ctx, G_ctx): c_.close()
    b.close()

print(f"\n{sum(1 for r in results if r[1])}/{len(results)} passed")
