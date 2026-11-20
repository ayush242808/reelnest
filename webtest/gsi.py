"""Google sign-in (ID-token flow) with a simulated Google Identity Services script and Supabase token endpoint."""
import json, hashlib, base64
from urllib.parse import urlparse
exec(open('/home/claude/webtest/features.py').read().split("reset_db()\nwith sync_playwright()")[0])
FAKE_GSI = r"""
window.google = { accounts: { id: {
  initialize(cfg) { window.__gsiCfg = cfg; },
  renderButton(el, opts) {
    const b = document.createElement('button'); b.id = 'fake-google'; b.textContent = 'Continue with Google'; b.dataset.theme = opts.theme;
    b.onclick = () => window.__gsiCfg.callback({ credential: 'hdr.' + btoa(JSON.stringify({ aud: window.__gsiCfg.client_id, nonce: window.__gsiCfg.nonce, email: 'ayush@example.com' })) + '.sig' });
    el.appendChild(b);
  } } } };
"""
seen = {}
def sb(route):
    u = urlparse(route.request.url)
    if u.path == "/auth/v1/token" and "grant_type=id_token" in u.query:
        body = json.loads(route.request.post_data); seen.update(body)
        payload = json.loads(base64.b64decode(body["id_token"].split(".")[1]))
        ok_nonce = hashlib.sha256(body["nonce"].encode()).hexdigest() == payload["nonce"]
        seen["nonce_ok"] = ok_nonce; seen["aud"] = payload["aud"]
        if not ok_nonce: return route.fulfill(status=400, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"}, body='{"error_description":"Nonces mismatch"}')
        uid = uid_for(payload["email"]); psql(f"insert into auth.users values ('{uid}') on conflict do nothing")
        return route.fulfill(status=200, content_type="application/json", headers={"Access-Control-Allow-Origin": "*"},
            body=json.dumps({"access_token": "tok:" + uid, "refresh_token": "ref:" + uid, "expires_in": 3600, "user": {"id": uid, "email": payload["email"]}}))
    return supabase(route)
reset_db()
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    for blocked in (False, True):
        ctx = b.new_context(viewport={"width": 1280, "height": 900}, color_scheme="dark")
        def handler(r):
            h = urlparse(r.request.url).hostname
            if h == "accounts.google.com":
                return r.abort() if blocked else r.fulfill(status=200, content_type="text/javascript", body=FAKE_GSI)
            if h == "test.supabase.co": return sb(r)
            if h in (None, ""): return r.continue_()
            return tmdb(r)
        ctx.route("**/*", handler)
        pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto(APP); pg.evaluate(f"() => {{ localStorage.clear(); localStorage.setItem('reelnest.tmdbKey','k'); localStorage.setItem('reelnest.sbUrl', '{SB}'); localStorage.setItem('reelnest.sbKey','anon-public-key-for-tests-0123456789'); }}")
        pg.reload(); pg.wait_for_timeout(300)
        # some local data first, to be merged on sign-in
        go_discover(pg); open_tile(pg, "3 Idiots"); pg.locator("[data-act=movie-watch]").click(); pg.wait_for_timeout(300)
        pg.locator(".src", has_text="Netflix").click(); pg.locator("[data-act=watch-save]").click(); pg.wait_for_timeout(300)
        pg.evaluate("location.hash='#profile'"); pg.wait_for_timeout(1200)
        if blocked:
            check("blocked Google script: clear message, email link still offered", "couldn't load" in pg.locator("#gsi-btn").inner_text() and pg.locator("[data-act=sb-send]").is_visible())
            check("no page errors (blocked)", not errs, errs); ctx.close(); continue
        check("Google button rendered in the sync card", pg.locator("#fake-google").is_visible())
        check("button uses the dark theme in dark mode", pg.locator("#fake-google").get_attribute("data-theme") == "filled_black")
        cfg = pg.evaluate("({ id: __gsiCfg.client_id, nonce: __gsiCfg.nonce, mode: __gsiCfg.ux_mode })")
        check("initialized with the public client ID and a hashed nonce (popup mode)", cfg["id"].startswith("437401470628-") and len(cfg["nonce"]) == 64 and cfg["mode"] == "popup", cfg)
        pg.evaluate("__reelnest.render && 0")
        pg.locator("[data-act=theme]").first.click() if pg.locator("[data-act=theme]").count() else None
        pg.wait_for_timeout(300)
        check("button survives re-renders", pg.locator("#fake-google").count() == 1, pg.locator("#gsi-btn").inner_html()[:200])
        pg.locator("#fake-google").click(); pg.wait_for_timeout(1500)
        check("token sent to Supabase with the matching raw nonce", seen.get("nonce_ok") is True and seen.get("provider") == "google", seen)
        merge = pg.locator("[data-act=sync-merge-ok]")
        check("first sign-in asks to merge (nothing overwritten)", merge.count() == 1)
        merge.click(); pg.wait_for_timeout(2500)
        row = psql("select (source->>'name') from rn_events where deleted_at is null")
        check("signed in with Google and local watch (with source) backed up", row == "Netflix", row)
        check("sync card shows the signed-in account", "ayush@example.com" in pg.locator("main").inner_text())
        check("no page errors (google)", not errs, errs)
        pg.screenshot(path="/home/claude/webtest/g1-signed-in.png"); ctx.close()
    b.close()
print(f"\n{sum(ok)}/{len(ok)} passed")
