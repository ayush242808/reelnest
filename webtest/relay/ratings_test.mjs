// Unit tests for supabase/functions/ratings/index.ts. Database calls run against the real SQL functions on the
// local PostgreSQL ("rt" database); TMDB, IMDb and Supabase Auth are simulated.
import fs from "node:fs";
import zlib from "node:zlib";
import { execFileSync } from "node:child_process";
const results = [];
const check = (n, c, i = "") => { results.push(!!c); console.log((c ? "PASS " : "FAIL ") + n + (c ? "" : "  :: " + String(i).slice(0, 300))); };
const ENV = { TMDB_KEY: "test-key-0123456789abcdef", SUPABASE_URL: "https://proj.supabase.co", SUPABASE_SECRET_KEYS: JSON.stringify({ default: "sb_secret_test" }), SUPABASE_ANON_KEY: "anon-test", RATINGS_TEST: "1" };
globalThis.Deno = { env: { get: (k) => ENV[k] }, serve: () => {} };
const run = (sql, asApi) => execFileSync("psql", ["-h", "/tmp", "-p", "5544", "-U", "postgres", "-d", "rt", "-qAt", "-v", "ON_ERROR_STOP=1"], { input: (asApi ? "set role service_role;\n" : "") + sql, encoding: "utf8", maxBuffer: 64e6 }).trim();
const psql = (sql) => run(sql, false);   // inspection, as the database owner
const api = (sql) => run(sql, true);     // what the function's server key can do
const q = (s) => "'" + String(s).replace(/'/g, "''") + "'";

let dataset = null, tmdbCalls = 0, tmdbDown = false, authCalls = 0;
const EXT = { "tmdb:movie:278": "tt0111161", "tmdb:series:1396": "tt0903747", "tmdb:movie:5": null };
globalThis.fetch = async (input, init = {}) => {
  const u = new URL(typeof input === "string" ? input : input.toString());
  if (u.hostname === "proj.supabase.co" && u.pathname === "/auth/v1/user") {
    authCalls++;
    const t = (init.headers.Authorization || "").slice(7);
    return t === "good-token" ? new Response(JSON.stringify({ id: "11111111-1111-1111-1111-111111111111" })) : new Response("{}", { status: 401 });
  }
  if (u.hostname === "proj.supabase.co" && u.pathname.startsWith("/rest/v1/rpc/")) {
    if (init.headers.apikey !== "sb_secret_test") return new Response("{}", { status: 401 });
    const fn = u.pathname.split("/").pop(), a = JSON.parse(init.body);
    if (fn === "rn_relay_take") return new Response("true");
    const sql = {
      rn_imdb_sync_begin: "select to_json(public.rn_imdb_sync_begin())",
      rn_imdb_sync_end: `select public.rn_imdb_sync_end(${Number(a.rows_seen)}, ${a.ok ? "true" : "false"}); select 'null'`,
      rn_imdb_ingest: a.chunk !== undefined ? `select to_json(public.rn_imdb_ingest($c$${a.chunk}$c$))` : "",
      rn_ratings_lookup: `select coalesce(json_agg(t), '[]') from public.rn_ratings_lookup(array[${(a.keys || []).map(q).join(",")}]::text[]) t`,
      rn_ratings_map: `select public.rn_ratings_map(${q(JSON.stringify(a.pairs))}::jsonb); select 'null'`,
    }[fn];
    const out = api(sql + ";").split("\n").filter((l) => l !== "f" && l !== "").join("\n");
    return new Response(out || "null", { status: 200 });
  }
  if (u.hostname === "api.themoviedb.org") {
    tmdbCalls++;
    if (tmdbDown) throw new Error("timeout");
    const m = u.pathname.match(/\/3\/(movie|tv)\/(\d+)\/external_ids$/);
    const key = `tmdb:${m[1] === "movie" ? "movie" : "series"}:${m[2]}`;
    if (!(key in EXT)) return new Response("{}", { status: 404 });
    return new Response(JSON.stringify({ imdb_id: EXT[key] }));
  }
  if (u.hostname === "datasets.imdbws.com") return new Response(dataset, { status: 200 });
  throw new Error("unexpected host " + u.hostname);
};

psql("truncate rn_private.imdb_ratings, rn_private.tmdb_imdb; update rn_private.imdb_sync set started_at = null, finished_at = null, status = null;");
fs.writeFileSync("/tmp/ratings_under_test.ts", fs.readFileSync("/home/claude/reelnest-repo/supabase/functions/ratings/index.ts", "utf8"));
const { handle } = await import("/tmp/ratings_under_test.ts");
const BASE = "https://proj.supabase.co/functions/v1/ratings", ORIGIN = "https://ayush242808.github.io";
const post = (body, token = "good-token") => handle(new Request(BASE, { method: "POST", headers: { Origin: ORIGIN, "Content-Type": "application/json", ...(token ? { Authorization: "Bearer " + token } : {}) }, body: typeof body === "string" ? body : JSON.stringify(body) }));
const syncCall = () => handle(new Request(BASE + "?op=sync"));

// ---- sync from a real-sized gzip ----
let tsv = "tconst\taverageRating\tnumVotes\ntt0111161\t9.3\t3012345\ntt0903747\t9.5\t2300000\ntt0000777\t6.1\t40\n";
for (let i = 1; i < 300000; i++) tsv += `tt9${String(i).padStart(7, "0")}\t${(10 + (i % 90)) / 10}\t${i % 7 === 0 ? 500 + i : 20}\n`;
dataset = zlib.gzipSync(Buffer.from(tsv));
let t0 = Date.now(), r = await syncCall(), body = await r.json();
check("sync loads the IMDb file (streamed, gzip, in chunks)", r.status === 200 && body.status === "ok" && body.lines >= 300000, JSON.stringify(body));
check("sync keeps titles with 100+ votes only", psql("select count(*) from rn_private.imdb_ratings;") === String(2 + Math.floor(299999 / 7)), psql("select count(*) from rn_private.imdb_ratings;"));
console.log(`   (sync of ${(tsv.length / 1e6).toFixed(1)} MB took ${Date.now() - t0} ms locally)`);
r = await syncCall(); body = await r.json();
check("a second sync the same day is skipped", body.status === "skipped");
psql("update rn_private.imdb_sync set started_at = now() - interval '2 days', finished_at = now() - interval '2 days', status = 'ok';");
dataset = zlib.gzipSync(Buffer.from("tconst\taverageRating\tnumVotes\ntt0111161\t1.0\t9\n"));
r = await syncCall(); body = await r.json();
check("a truncated file is rejected and existing ratings are kept", r.status === 500 && psql("select rating from rn_private.imdb_ratings where tconst = 'tt0111161';") === "9.3", JSON.stringify(body));
check("...and the failure is recorded", psql("select status from rn_private.imdb_sync;") === "failed");

// ---- lookups ----
r = await post({ keys: ["tmdb:movie:278"] }, null);
check("lookup without sign-in is refused", r.status === 401);
r = await post({ keys: ["tmdb:movie:278"] }, "stolen-or-expired");
check("lookup with an invalid session is refused", r.status === 401);
tmdbCalls = 0;
r = await post({ keys: ["tmdb:movie:278", "tmdb:series:1396", "tmdb:movie:5", "tmdb:movie:999"] }); body = await r.json();
check("signed-in lookup returns IMDb rating and votes", r.status === 200 && body.ratings["tmdb:movie:278"].r === 9.3 && body.ratings["tmdb:movie:278"].v === 3012345 && body.ratings["tmdb:series:1396"].r === 9.5, JSON.stringify(body));
check("titles with no IMDb entry come back as null", body.ratings["tmdb:movie:5"] === null && body.ratings["tmdb:movie:999"] === null, JSON.stringify(body));
check("CORS only for the ReelNest origin", r.headers.get("Access-Control-Allow-Origin") === ORIGIN);
const firstCalls = tmdbCalls; tmdbCalls = 0;
r = await post({ keys: ["tmdb:movie:278", "tmdb:series:1396"] }); body = await r.json();
check("IMDb ids are looked up once and then cached", firstCalls === 4 && tmdbCalls === 0 && body.ratings["tmdb:movie:278"].r === 9.3, `${firstCalls} then ${tmdbCalls}`);
tmdbDown = true;
r = await post({ keys: ["tmdb:movie:77"] }); body = await r.json();
check("if TMDB is down the title is left pending, not cached as 'no rating'", r.status === 200 && !("tmdb:movie:77" in body.ratings) && body.pending === 1, JSON.stringify(body));
tmdbDown = false;
const many = Array.from({ length: 50 }, (_, i) => "tmdb:movie:" + (1000 + i));
tmdbCalls = 0; r = await post({ keys: many }); body = await r.json();
check("at most 30 new id lookups per request; the rest are pending", tmdbCalls === 30 && body.pending === 20, `${tmdbCalls} ${body.pending}`);
for (const [bad, why] of [[{ keys: Array(61).fill(0).map((_, i) => "tmdb:movie:" + i) }, "more than 60 keys"], [{ keys: ["'; drop table x;--"] }, "malformed key"], ["not json", "bad JSON"], [{ keys: [] }, "empty"]]) {
  r = await post(bad); check("rejected: " + why, r.status === 400, r.status);
}
r = await handle(new Request(BASE, { method: "GET", headers: { Origin: ORIGIN } }));
check("other methods refused", r.status === 405);
const n0 = authCalls; await post({ keys: ["tmdb:movie:278"] }); await post({ keys: ["tmdb:movie:278"] });
check("the session check is cached briefly (no auth call per request)", authCalls === n0);
console.log(`\n${results.filter(Boolean).length}/${results.length} passed`);
