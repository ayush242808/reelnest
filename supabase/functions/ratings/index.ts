// ReelNest public-ratings function (Supabase Edge Function "ratings").
//
// What it does
//  * POST  /ratings            {keys: ["tmdb:movie:278", ...]}  ->  {ratings: {key: {r, v, id} | null}, pending}
//    IMDb audience rating (r, 1-10) and vote count (v) for up to 60 TMDB titles. Signed-in ReelNest users only.
//  * GET   /ratings?op=sync    Daily refresh from IMDb's official dataset (called by pg_cron). Runs at most once per
//    20 hours whoever calls it, so it is safe to leave unauthenticated.
//
// Why IMDb: real people's votes, published by IMDb itself for personal/non-commercial use
// (https://developer.imdb.com/non-commercial-datasets/). Not scraped, not paid reviews. IMDb doesn't allow
// republishing the data as a public database, so it is stored where no API role can read it and only returned
// to signed-in users of this private app, a page of titles at a time.
//
// Setup: Edge Functions > ratings, "Verify JWT" OFF (auth is checked below; the cron call has no user).
// Uses the existing TMDB_KEY secret to map TMDB ids to IMDb ids. Monitoring: Logs, events "ratings_*".

const ALLOWED_ORIGINS = ["https://ayush242808.github.io"];
const DATASET = "https://datasets.imdbws.com/title.ratings.tsv.gz";
const KEY_RE = /^tmdb:(movie|series):\d{1,9}$/;
const MAX_KEYS = 60;
const MAP_PER_REQUEST = 30;        // TMDB external_ids lookups per request (the rest come back as "pending")
const CHUNK_CHARS = 2_000_000;     // ~2 MB of TSV per database call
const LIMITS = { perUser: { n: 120, win: 300 }, mapGlobal: { n: 6000, win: 86400 } };

const json = (status: number, obj: unknown, headers: Record<string, string>) =>
  new Response(JSON.stringify(obj), { status, headers: { ...headers, "Content-Type": "application/json", "Cache-Control": "no-store" } });
const log = (evt: string, data: Record<string, unknown>) => console.log(JSON.stringify({ evt, ...data }));

function serverKey(): Record<string, string> | null {
  try {
    const keys = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") || "{}");
    const k = keys.default || Object.values(keys)[0];
    if (typeof k === "string" && k) return { apikey: k };
  } catch { /* fall through */ }
  const legacy = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  return legacy ? { apikey: legacy, Authorization: `Bearer ${legacy}` } : null;
}
async function rpc(name: string, args: unknown, timeoutMs = 10000) {
  const key = serverKey(), url = Deno.env.get("SUPABASE_URL");
  if (!key || !url) throw new Error("server not configured");
  const r = await fetch(`${url}/rest/v1/rpc/${name}`, {
    method: "POST", headers: { ...key, "Content-Type": "application/json" }, body: JSON.stringify(args), signal: AbortSignal.timeout(timeoutMs),
  });
  if (!r.ok) throw new Error(`${name} ${r.status} ${(await r.text()).slice(0, 160)}`);
  return r.status === 204 ? null : await r.json();
}
async function take(bucket: string, n: number, win: number) {
  try { return (await rpc("rn_relay_take", { p_bucket: bucket, p_limit: n, p_window_seconds: win }, 1500)) === true; }
  catch (e) { log("ratings_limiter_unavailable", { msg: String(e).slice(0, 100) }); return true; } // per-user check below still applies
}

// ---- who is calling: a signed-in user of this Supabase project ----
const users = new Map<string, { id: string; until: number }>();
async function userOf(req: Request): Promise<string | null> {
  const token = (req.headers.get("Authorization") || "").replace(/^Bearer\s+/i, "");
  if (!token || token.length > 4096) return null;
  const hit = users.get(token);
  if (hit && hit.until > Date.now()) return hit.id;
  const url = Deno.env.get("SUPABASE_URL"), apikey = Deno.env.get("SUPABASE_ANON_KEY") || serverKey()?.apikey || "";
  try {
    const r = await fetch(`${url}/auth/v1/user`, { headers: { apikey, Authorization: `Bearer ${token}` }, signal: AbortSignal.timeout(4000) });
    if (!r.ok) return null;
    const u = await r.json();
    if (!u || typeof u.id !== "string") return null;
    if (users.size > 500) users.clear();
    users.set(token, { id: u.id, until: Date.now() + 5 * 60 * 1000 });
    return u.id;
  } catch { return null; }
}

// ---- TMDB id -> IMDb id ----
async function imdbIdFor(key: string): Promise<string | null | undefined> {
  const tmdb = Deno.env.get("TMDB_KEY") || "";
  if (!tmdb) return undefined;
  const [, kind, id] = key.split(":");
  const u = new URL(`https://api.themoviedb.org/3/${kind === "movie" ? "movie" : "tv"}/${id}/external_ids`);
  const headers: Record<string, string> = { Accept: "application/json" };
  if (tmdb.startsWith("eyJ")) headers.Authorization = "Bearer " + tmdb; else u.searchParams.set("api_key", tmdb);
  try {
    const r = await fetch(u, { headers, signal: AbortSignal.timeout(6000) });
    if (r.status === 404) return null;
    if (!r.ok) return undefined; // try again next time
    const d = await r.json();
    return typeof d.imdb_id === "string" && /^tt\d{1,12}$/.test(d.imdb_id) ? d.imdb_id : null;
  } catch { return undefined; }
}

// ---- daily IMDb sync ----
async function sync(): Promise<Response> {
  const may = await rpc("rn_imdb_sync_begin", {});
  if (may !== true) return json(200, { status: "skipped", reason: "synced recently" }, {});
  const t0 = Date.now();
  let lines = 0, written = 0, buf = "";
  try {
    const up = await fetch(DATASET, { signal: AbortSignal.timeout(60000) });
    if (!up.ok || !up.body) throw new Error("dataset " + up.status);
    const text = up.body.pipeThrough(new DecompressionStream("gzip")).pipeThrough(new TextDecoderStream());
    const flush = async (part: string) => { written += Number(await rpc("rn_imdb_ingest", { chunk: part }, 70000)) || 0; };
    for await (const piece of text) {
      buf += piece;
      if (buf.length >= CHUNK_CHARS) {
        const cut = buf.lastIndexOf("\n") + 1;
        const part = buf.slice(0, cut); buf = buf.slice(cut);
        lines += part.split("\n").length - 1;
        await flush(part);
      }
    }
    if (buf) { lines += buf.split("\n").length; await flush(buf); }
    if (lines < 100000) throw new Error("dataset looked truncated: " + lines + " lines"); // never trust a short file
    await rpc("rn_imdb_sync_end", { rows_seen: lines, ok: true });
    log("ratings_sync", { lines, written, ms: Date.now() - t0 });
    return json(200, { status: "ok", lines, written }, {});
  } catch (e) {
    log("ratings_sync_failed", { msg: String(e).slice(0, 160), lines, ms: Date.now() - t0 });
    try { await rpc("rn_imdb_sync_end", { rows_seen: lines, ok: false }); } catch { /* ignore */ }
    return json(500, { status: "failed" }, {});
  }
}

export async function handle(req: Request): Promise<Response> {
  const origin = req.headers.get("Origin") || "";
  const cors: Record<string, string> = { "Vary": "Origin", "X-Content-Type-Options": "nosniff" };
  if (ALLOWED_ORIGINS.includes(origin)) {
    cors["Access-Control-Allow-Origin"] = origin;
    cors["Access-Control-Allow-Methods"] = "POST, OPTIONS";
    cors["Access-Control-Allow-Headers"] = "Authorization, Content-Type, apikey";
    cors["Access-Control-Max-Age"] = "86400";
  }
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
  const url = new URL(req.url);
  if (req.method === "GET" && url.searchParams.get("op") === "sync") return sync();
  if (req.method !== "POST") return json(405, { error: "method not allowed" }, { ...cors, Allow: "POST, OPTIONS" });

  const uid = await userOf(req);
  if (!uid) return json(401, { error: "sign in to see ratings" }, cors);
  if (!(await take("rat:" + uid, LIMITS.perUser.n, LIMITS.perUser.win))) {
    log("ratings_limit", { kind: "user" });
    return json(429, { error: "too many requests" }, { ...cors, "Retry-After": "300" });
  }
  let keys: string[];
  try {
    const body = await req.json();
    keys = Array.isArray(body?.keys) ? [...new Set(body.keys as unknown[])].filter((k): k is string => typeof k === "string" && KEY_RE.test(k)) : [];
  } catch { return json(400, { error: "invalid body" }, cors); }
  if (!keys.length || keys.length > MAX_KEYS) return json(400, { error: `send 1-${MAX_KEYS} keys` }, cors);

  try {
    let rows = await rpc("rn_ratings_lookup", { keys }) as { tmdb_key: string; imdb_id: string | null; rating: number | null; votes: number | null; needs_map: boolean }[];
    const toMap = rows.filter((r) => r.needs_map).map((r) => r.tmdb_key);
    let pending = Math.max(0, toMap.length - MAP_PER_REQUEST);
    const batch = toMap.slice(0, MAP_PER_REQUEST);
    if (batch.length && (await take("map:global", LIMITS.mapGlobal.n, LIMITS.mapGlobal.win))) {
      const found: { k: string; imdb: string | null }[] = [];
      for (let i = 0; i < batch.length; i += 6) {
        const part = batch.slice(i, i + 6);
        const ids = await Promise.all(part.map(imdbIdFor));
        part.forEach((k, j) => { if (ids[j] !== undefined) found.push({ k, imdb: ids[j] as string | null }); else pending++; });
      }
      if (found.length) { await rpc("rn_ratings_map", { pairs: found }); rows = await rpc("rn_ratings_lookup", { keys }); }
    } else if (batch.length) { pending += batch.length; log("ratings_limit", { kind: "map" }); }
    const ratings: Record<string, { r: number; v: number; id: string } | null> = {};
    for (const r of rows) {
      if (r.needs_map) continue; // not known yet: leave it out so the app asks again later
      ratings[r.tmdb_key] = r.imdb_id && r.rating != null ? { r: Number(r.rating), v: Number(r.votes), id: r.imdb_id } : null;
    }
    return json(200, { ratings, pending }, cors);
  } catch (e) {
    log("ratings_error", { msg: String(e).slice(0, 160) });
    return json(502, { error: "ratings unavailable" }, cors);
  }
}

if (typeof Deno !== "undefined" && Deno.serve && !Deno.env.get("RATINGS_TEST")) Deno.serve(handle);
