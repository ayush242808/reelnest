// Unit tests for supabase/functions/tmdb/index.ts with Deno + network shims.
import fs from "node:fs";
const results = [];
const check = (n, c, i = "") => { results.push(!!c); console.log((c ? "PASS " : "FAIL ") + n + (c ? "" : "  :: " + String(i).slice(0, 300))); };
const ENV = { TMDB_KEY: "test-key-0123456789abcdef", SUPABASE_URL: "https://proj.supabase.co", SUPABASE_SECRET_KEYS: JSON.stringify({ default: "sb_secret_test" }) };
let handler = null;
globalThis.Deno = { env: { get: (k) => ENV[k] }, serve: (h) => { handler = h; } };
// network mock
const calls = []; let limiterMode = "db"; const counters = new Map(); let upstream = null;
globalThis.fetch = async (input, init = {}) => {
  const u = new URL(typeof input === "string" ? input : input.toString()); calls.push({ url: u.toString(), init });
  if (u.hostname === "proj.supabase.co") {
    if (limiterMode === "down") throw new Error("connect refused");
    if (init.headers.apikey !== "sb_secret_test") return new Response("{}", { status: 401 });
    const b = JSON.parse(init.body); const k = b.p_bucket + "|" + b.p_window_seconds;
    counters.set(k, (counters.get(k) || 0) + 1); return new Response(JSON.stringify(counters.get(k) <= b.p_limit), { status: 200 });
  }
  return upstream(u, init);
};
const src = fs.readFileSync("/home/claude/reelnest-repo/supabase/functions/tmdb/index.ts", "utf8");
fs.writeFileSync("/tmp/relay_under_test.ts", src);
await import("/tmp/relay_under_test.ts");
const BASE = "https://proj.supabase.co/functions/v1/tmdb";
const ORIGIN = "https://ayush242808.github.io";
const call = (path, { method = "GET", origin = ORIGIN, ip = "1.2.3.4" } = {}) => handler(new Request(BASE + path, { method, headers: { ...(origin ? { Origin: origin } : {}), "x-forwarded-for": ip } }));
upstream = async (u) => u.hostname === "api.themoviedb.org"
  ? new Response(JSON.stringify({ results: [{ id: 1, title: "3 Idiots" }], echo: u.pathname }), { status: 200, headers: { "Content-Type": "application/json" } })
  : new Response(new Uint8Array([137, 80, 78, 71]), { status: 200, headers: { "Content-Type": "image/png" } });

let r = await call("/3/search/multi?query=3%20idiots&page=1&language=en-US&include_adult=false");
let body = await r.text(); let up = calls.filter((c) => c.url.includes("themoviedb")).pop();
check("allowed search works", r.status === 200 && body.includes("3 Idiots"), r.status + body);
check("key added server-side, never in the response", up.url.includes("api_key=test-key") && !body.includes("test-key"));
check("CORS header only for the ReelNest origin", r.headers.get("Access-Control-Allow-Origin") === ORIGIN);
check("include_adult forced false", up.url.includes("include_adult=false"));
for (const p of ["/3/trending/all/week?language=en-US&page=1", "/3/discover/movie?with_origin_country=IN&sort_by=popularity.desc&primary_release_date.gte=2025-05-20&vote_average.gte=6.8&vote_count.gte=15&page=1&language=en-US&include_adult=false",
  "/3/discover/tv?without_genres=16%2C10762%2C10763%2C10764%2C10766%2C10767&air_date.gte=2026-05-20&vote_average.gte=7.3&vote_count.gte=100&sort_by=popularity.desc&page=1&language=en-US&include_adult=false",
  "/3/movie/20453?language=en-US&append_to_response=credits%2Calternative_titles%2Crelease_dates%2Cvideos&include_video_language=en%2Chi%2Cnull",
  "/3/tv/95557?language=en-US&append_to_response=credits%2Caggregate_credits%2Calternative_titles%2Ccontent_ratings%2Cvideos%2Cexternal_ids&include_video_language=en%2Chi%2Cnull",
  "/3/tv/95557/season/1?language=en-US", "/3/movie/20453/watch/providers", "/3/genre/movie/list?language=en-US"]) {
  r = await call(p); check("app request allowed: " + p.split("?")[0], r.status === 200, r.status + " " + (await r.text()));
}
for (const [p, why] of [["/3/account", "account endpoint"], ["/3/movie/1/account_states", "user-state endpoint"], ["/3/authentication/token/new", "auth endpoint"], ["/3/../../etc/passwd", "path traversal"], ["/3/person/1", "unused endpoint"], ["/v4/list/1", "v4"], ["/https://evil.example/x", "other host"]]) {
  r = await call(p); check(`rejected (${why})`, r.status === 404, r.status);
}
for (const [p, why] of [["/3/search/multi?query=x&api_key=someone-elses", "api_key param"], ["/3/search/multi?query=x&foo=1", "unknown param"], ["/3/search/multi?query=x&page=0", "page 0"],
  ["/3/search/multi?query=" + "a".repeat(101), "oversized query"], ["/3/search/multi?query=x&query=y", "duplicate param"], ["/3/discover/movie?sort_by=revenue.desc;drop", "bad sort"],
  ["/3/discover/movie?with_origin_country=india", "bad country"], ["/3/movie/1?append_to_response=account_states", "append not allowed"], ["/3/search/multi?query=x&include_adult=true", "adult content"]]) {
  r = await call(p); check(`invalid input refused (${why})`, r.status === 400, r.status);
}
for (const m of ["POST", "PUT", "DELETE", "PATCH"]) { r = await call("/3/search/multi?query=x", { method: m }); check(`${m} refused`, r.status === 405, r.status); }
r = await call("/3/search/multi?query=x", { method: "OPTIONS" }); check("OPTIONS preflight ok", r.status === 204 && r.headers.get("Access-Control-Allow-Methods") === "GET, OPTIONS");
r = await call("/3/search/multi?query=x", { origin: "https://evil.example" }); check("other site's browser is refused (no CORS grant)", r.status === 403 && !r.headers.get("Access-Control-Allow-Origin"));
r = await call("/3/search/multi?query=x", { origin: null }); check("no Origin (script) refused for catalog calls", r.status === 403);
r = await call("/img/w342/abcdef123.jpg", { origin: null }); check("images work without Origin (img tags)", r.status === 200 && r.headers.get("Content-Type") === "image/png");
for (const p of ["/img/w342/../../x.jpg", "/img/w9999/abc12.jpg", "/img/w342/abc12.exe", "/img/w342/abc12.jpg?x=1"]) { r = await call(p); check("bad image path refused: " + p, r.status === 400 || r.status === 404, r.status); }
// upstream error text is never forwarded
upstream = async () => new Response(JSON.stringify({ status_message: "Invalid API key: test-key-0123456789abcdef" }), { status: 401 });
r = await call("/3/search/multi?query=err1"); body = await r.text(); check("upstream error text not forwarded (no key leak)", r.status === 502 && !body.includes("test-key"), body);
// timeout
upstream = (u, init) => new Promise((_, rej) => init.signal.addEventListener("abort", () => rej(new Error("aborted"))));
const keepAlive = setInterval(() => {}, 1000); const t0 = Date.now(); r = await call("/3/search/multi?query=slow"); check("slow upstream -> 504 within the timeout", r.status === 504 && Date.now() - t0 < 9500, (Date.now() - t0) + "ms"); clearInterval(keepAlive);
// size cap
upstream = async () => new Response("x".repeat(1_600_000), { status: 200, headers: { "Content-Type": "application/json" } });
r = await call("/3/search/multi?query=huge"); check("oversized upstream response refused", r.status === 502);
// cache
let n = 0; upstream = async () => { n++; return new Response('{"results":[]}', { status: 200 }); };
await call("/3/genre/tv/list?language=hi-IN"); r = await call("/3/genre/tv/list?language=hi-IN");
check("repeat request served from cache (one upstream call)", n === 1 && r.headers.get("X-Relay-Cache") === "hit", n);
// rate limiting (server-side, via the limiter function with the server key)
const lim = calls.find((c) => c.url.endsWith("/rest/v1/rpc/rn_relay_take"));
check("limiter called with the server key, bucket is a hash (no IP stored)", lim && lim.init.headers.apikey === "sb_secret_test" && !lim.init.body.includes("1.2.3.4") && /"api:[0-9a-f]{24}"/.test(lim.init.body), lim && lim.init.body);
upstream = async () => new Response('{"results":[]}', { status: 200 });
let got429 = null;
for (let i = 0; i < 320; i++) { r = await call("/3/search/multi?query=q" + i, { ip: "9.9.9.9" }); if (r.status === 429) { got429 = i; break; } }
check("per-client limit returns 429 (with Retry-After)", got429 !== null && got429 <= 300 && r.headers.get("Retry-After") === "300", got429);
r = await call("/3/search/multi?query=other", { ip: "8.8.8.8" }); check("other clients unaffected", r.status === 200, r.status);
limiterMode = "down"; let fb = null;
for (let i = 0; i < 320; i++) { r = await call("/3/search/multi?query=d" + i, { ip: "7.7.7.7" }); if (r.status === 429) { fb = i; break; } }
check("limiter DB unreachable: still limited in-instance (fail soft)", fb !== null && fb <= 300, fb);
check("no request ever went to a host other than TMDB or the project", calls.every((c) => /^(api\.themoviedb\.org|image\.tmdb\.org|proj\.supabase\.co)$/.test(new URL(c.url).hostname)));
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
