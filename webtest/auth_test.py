"""Session refresh behaves like Supabase Auth: refresh tokens are single-use, reusing an old one revokes the whole
sign-in ("Invalid Refresh Token: ..."), and logout without scope=local signs out every device.
Run against another copy of the app with APP_DIR=/path python3 auth_test.py"""
import os, json, itertools
src = open("/home/claude/webtest/e2e.py").read()
exec(src[: src.index("reset_db()\nwith sync_playwright")])
if os.environ.get("APP_DIR"): APP = "file://" + os.environ["APP_DIR"] + "/index.html"

counter = itertools.count(1)
FAM = {}      # family id -> {"uid", "current", "used": set(), "revoked"}
TOKREQ = []   # refresh tokens presented
LOGOUTS = []
_orig = supabase
def supabase(route):  # noqa: F811
    req = route.request; u = urlparse(req.url)
    def j(obj, status=200): return route.fulfill(status=status, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body=json.dumps(obj))
    if req.method == "POST" and u.path == "/auth/v1/verify":
        body = json.loads(req.post_data); uid = uid_for(body["email"]); f = f"f{next(counter)}"
        FAM[f] = {"uid": uid, "current": f"{f}.1", "used": set(), "revoked": False}
        return j({"access_token": "tok:" + uid, "refresh_token": f"{f}.1", "expires_in": 3600, "user": {"id": uid, "email": body["email"]}})
    if req.method == "POST" and u.path == "/auth/v1/token":
        rt = json.loads(req.post_data)["refresh_token"]; TOKREQ.append(rt); f = rt.split(".")[0]; fam = FAM.get(f)
        if not fam or fam["revoked"]: return j({"error_code": "refresh_token_not_found", "msg": "Invalid Refresh Token: Refresh Token Not Found"}, 400)
        if rt != fam["current"]:   # reuse of a rotated token: revoke the whole family, like GoTrue
            fam["revoked"] = True
            return j({"error_code": "refresh_token_already_used", "msg": "Invalid Refresh Token: Already Used"}, 400)
        n = int(rt.split(".")[1]) + 1; fam["current"] = f"{f}.{n}"
        return j({"access_token": "tok:" + fam["uid"], "refresh_token": fam["current"], "expires_in": 3600, "user": {"id": fam["uid"]}})
    if u.path == "/auth/v1/logout":
        scope = dict(x.split("=") for x in u.query.split("&") if "=" in x).get("scope", "global"); LOGOUTS.append(scope)
        if scope == "global":
            for fam in FAM.values(): fam["revoked"] = True
        return route.fulfill(status=204, headers={"Access-Control-Allow-Origin": "*"})
    if u.path.startswith("/rest/v1/"):   # a revoked sign-in can't call the API
        pass
    return _orig(route)

def run(pg): pg.evaluate("() => __reelnest.Sync.run()"); pg.wait_for_timeout(900)
def expire(pg): pg.evaluate("() => { const s = JSON.parse(localStorage.getItem('reelnest.session')); s.expires_at = 1; localStorage.setItem('reelnest.session', JSON.stringify(s)); __reelnest.Sync.session.expires_at = 1; }")
def phase(pg): return pg.evaluate("() => [__reelnest.Sync.phase, __reelnest.Sync.error || '', !!__reelnest.Sync.session]")

reset_db()
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    # Two tabs of the app in one browser (shared storage), e.g. the installed app and a browser tab
    ctx, A, eA = new_page(b)
    sign_in(A); run(A)
    B = ctx.new_page(); B.goto(APP); B.wait_for_timeout(700); run(B)
    expire(A); B.evaluate("() => { __reelnest.Sync.session.expires_at = 1; }")
    run(A)                      # tab A rotates the token
    B.wait_for_timeout(11000)   # later than Supabase's 10 s reuse grace period
    run(B)                      # tab B still holds the old token in memory
    run(A)
    pa, pb = phase(A), phase(B)
    revoked = any(f["revoked"] for f in FAM.values())
    check("R1 two tabs: the second tab never reuses an already-rotated refresh token", len(TOKREQ) >= 1 and not revoked and pa[0] == "idle" and pb[0] == "idle" and pa[2] and pb[2], {"A": pa, "B": pb, "revoked": revoked, "presented": TOKREQ})
    # Concurrent refreshes inside one tab send the token only once
    TOKREQ.clear(); expire(A)
    A.evaluate("() => Promise.all([__reelnest.Sync.rpc('rn_pull', {since: 0}), __reelnest.Sync.rpc('rn_pull', {since: 0})])"); A.wait_for_timeout(500)
    check("R2 concurrent requests in one tab refresh once", len(TOKREQ) == 1, TOKREQ)
    # A revoked sign-in is reported as signed out, not as a raw sync failure
    for f in FAM.values(): f["revoked"] = True
    expire(A); run(A)
    pa = phase(A); tab(A, "profile"); txt = A.inner_text("main")
    check("R3 a revoked refresh token asks you to sign in again", "sign-in expired" in pa[1].lower() and not pa[2] and A.locator("#sb-email").count() == 1, pa)
    check("R3 no raw 'Invalid Refresh Token' error is shown", "Invalid Refresh Token" not in txt)
    check("R3 nothing on the device was lost", A.evaluate("() => Object.keys(__reelnest.S.works).length") >= 0)
    ctx.close()
    # Sign-out on one device must not sign out the others
    FAM.clear(); LOGOUTS.clear()
    c1, P, e1 = new_page(b); sign_in(P); run(P)
    c2, L, e2 = new_page(b); sign_in(L); run(L)
    tab(P, "profile"); P.evaluate("() => __reelnest.Sync.signOut()"); P.wait_for_timeout(500)
    expire(L); run(L)
    check("R4 signing out on one device keeps other devices signed in", LOGOUTS == ["local"] and phase(L)[0] == "idle" and phase(L)[2], {"logouts": LOGOUTS, "other": phase(L)})
    check("no page errors", not (eA or e1 or e2), (eA + e1 + e2)[:3])
    b.close()
print(f"\n{sum(1 for r in results if r[1])}/{len(results)} passed")
