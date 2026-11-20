// ReelNest shared TMDB relay (Supabase Edge Function "tmdb").
//
// Purpose: lets people use the ReelNest site without their own TMDB key, and routes around Indian ISPs
// that block themoviedb.org. The TMDB credential stays on the server (secret TMDB_KEY).
//
// Threat model, honestly: this endpoint is public (browsing works before sign-in), so anyone can call it.
// The Origin check below is a browser control only — a script can send any Origin. What actually limits
// abuse is server-side: a strict allowlist of TMDB paths/parameters (read-only catalog data, nothing
// else), response-size caps, timeouts, per-client and global rate limits stored in Postgres, and caching.
// Worst case for a determined abuser is consuming the daily global budget, after which the relay refuses
// until the next day; it can never be used to reach other hosts or to read the key.
//
// Setup (Supabase dashboard): Edge Functions › Secrets: TMDB_KEY. Function settings: "Verify JWT" OFF.
// Monitoring: Edge Functions › tmdb › Logs (search for "relay_limit" / "relay_upstream"), and the
// usage query in README.md (rn_private.relay_hits).

const ALLOWED_ORIGINS = ["https://ayush242808.github.io"];
const LIMITS = {
  apiPerClient: { n: 300, win: 300 },     // 300 catalog calls / 5 min per client (a busy session uses < 100)
  imgPerClient: { n: 900, win: 300 },     // images are only a fallback path
  apiGlobal: { n: 25000, win: 86400 },    // whole site, per day
  imgGlobal: { n: 40000, win: 86400 },
};
const UPSTREAM_TIMEOUT_MS = 8000;
const MAX_API_BYTES = 1_500_000;
const MAX_IMG_BYTES = 5_000_000;

// Only what ReelNest calls (see Catalog in index.html).
const PATHS = [
  /^search\/(multi|movie|tv)$/,
  /^trending\/(all|movie|tv)\/(day|week)$/,
  /^discover\/(movie|tv)$/,
  /^(movie|tv)\/\d{1,9}$/,
  /^tv\/\d{1,9}\/season\/\d{1,3}$/,
  /^(movie|tv)\/\d{1,9}\/watch\/providers$/,
  /^genre\/(movie|tv)\/list$/,
];
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const PARAMS: Record<string, RegExp> = {
  query: /^[^\u0000-\u001f]{1,100}$/,
  page: /^([1-9]\d{0,2})$/,
  language: /^[a-z]{2}(-[A-Z]{2})?$/,
  region: /^[A-Z]{2}$/,
  watch_region: /^[A-Z]{2}$/,
  include_adult: /^false$/,
  include_video_language: /^[a-z,]{2,20}$|^[a-z]{2}(,[a-z]{2})*,null$/,
  append_to_response: /^(credits|aggregate_credits|alternative_titles|release_dates|content_ratings|videos|external_ids)(,(credits|aggregate_credits|alternative_titles|release_dates|content_ratings|videos|external_ids)){0,6}$/,
  sort_by: /^(popularity|vote_average|primary_release_date|first_air_date|release_date)\.(asc|desc)$/,
  with_genres: /^[\d,|]{1,60}$/,
  without_genres: /^[\d,|]{1,60}$/,
  with_original_language: /^[a-z]{2}$/,
  with_origin_country: /^[A-Z]{2}$/,
  year: /^\d{4}$/,
  primary_release_year: /^\d{4}$/,
  first_air_date_year: /^\d{4}$/,
  "primary_release_date.gte": DATE, "primary_release_date.lte": DATE,
  "first_air_date.gte": DATE, "first_air_date.lte": DATE,
  "air_date.gte": DATE, "air_date.lte": DATE,
  "vote_average.gte": /^\d{1,2}(\.\d)?$/,
  "vote_count.gte": /^\d{1,6}$/,
};
const IMG = /^\/img\/(w92|w154|w185|w342|w500|w780|w1280)\/[A-Za-z0-9_-]{5,64}\.(jpg|jpeg|png|webp|svg)$/;

const json = (status: number, obj: unknown, headers: Record<string, string>) =>
  new Response(JSON.stringify(obj), { status, headers: { ...headers, "Content-Type": "application/json", "Cache-Control": "no-store" } });
const log = (evt: string, data: Record<string, unknown>) => console.log(JSON.stringify({ evt, ...data }));

// ---- server-side rate limiting (Postgres, via a function only the service role may call) ----
function serverKey(): { headers: Record<string, string> } | null {
  try {
    const keys = JSON.parse(Deno.env.get("SUPABASE_SECRET_KEYS") || "{}");
    const k = keys.default || Object.values(keys)[0];
    if (typeof k === "string" && k) return { headers: { apikey: k } };
  } catch { /* fall through */ }
  const legacy = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  return legacy ? { headers: { apikey: legacy, Authorization: `Bearer ${legacy}` } } : null;
}
const memo = new Map<string, { hits: number; until: number }>(); // per-instance fallback if the DB is unreachable
function memTake(bucket: string, n: number, win: number) {
  const now = Date.now(), e = memo.get(bucket);
  if (!e || e.until < now) { memo.set(bucket, { hits: 1, until: now + win * 1000 }); if (memo.size > 5000) memo.clear(); return true; }
  e.hits++; return e.hits <= n;
}
async function take(bucket: string, n: number, win: number): Promise<boolean> {
  const key = serverKey(), url = Deno.env.get("SUPABASE_URL");
  if (!key || !url) return memTake(bucket, n, win);
  try {
    const r = await fetch(`${url}/rest/v1/rpc/rn_relay_take`, {
      method: "POST", headers: { ...key.headers, "Content-Type": "application/json" },
      body: JSON.stringify({ p_bucket: bucket, p_limit: n, p_window_seconds: win }), signal: AbortSignal.timeout(1500),
    });
    if (!r.ok) throw new Error("limiter " + r.status);
    return (await r.json()) === true;
  } catch (e) {
    log("relay_limiter_unavailable", { msg: String(e).slice(0, 120) });
    return memTake(bucket, n, win); // fail soft: still limited per instance
  }
}
async function clientBucket(req: Request, kind: string) {
  const ip = (req.headers.get("x-forwarded-for") || "").split(",")[0].trim() || req.headers.get("cf-connecting-ip") || "unknown";
  const pepper = Deno.env.get("TMDB_KEY") || "reelnest"; // server-only, so the stored bucket can't be reversed to an IP
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(`${kind}|${ip}|${pepper}`));
  return kind + ":" + [...new Uint8Array(d)].slice(0, 12).map((b) => b.toString(16).padStart(2, "0")).join("");
}

// ---- small per-instance cache (TMDB allows caching; keeps quota use down) ----
const cache = new Map<string, { at: number; body: Uint8Array; type: string }>();
const CACHE_MS = 10 * 60 * 1000;

Deno.serve(async (req: Request) => {
  const origin = req.headers.get("Origin") || "";
  const cors: Record<string, string> = { "Vary": "Origin", "X-Content-Type-Options": "nosniff" };
  if (ALLOWED_ORIGINS.includes(origin)) {
    cors["Access-Control-Allow-Origin"] = origin; // CORS lets the ReelNest page read responses; it is not authentication
    cors["Access-Control-Allow-Methods"] = "GET, OPTIONS";
    cors["Access-Control-Allow-Headers"] = "Accept";
    cors["Access-Control-Max-Age"] = "86400";
  }
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
  if (req.method !== "GET") return json(405, { error: "method not allowed" }, { ...cors, Allow: "GET, OPTIONS" });

  const url = new URL(req.url);
  const at = url.pathname.indexOf("/tmdb");
  const rest = at >= 0 ? url.pathname.slice(at + 5) : url.pathname;
  if (rest === "" || rest === "/") return new Response("ReelNest TMDB relay is running.", { headers: { ...cors, "Content-Type": "text/plain" } });

  // ---- images ----
  if (rest.startsWith("/img/")) {
    if (!IMG.test(rest) || url.search) return json(400, { error: "invalid image path" }, cors);
    if (!(await take(await clientBucket(req, "img"), LIMITS.imgPerClient.n, LIMITS.imgPerClient.win)) ||
        !(await take("img:global", LIMITS.imgGlobal.n, LIMITS.imgGlobal.win))) {
      log("relay_limit", { kind: "img" });
      return json(429, { error: "too many requests" }, { ...cors, "Retry-After": "300" });
    }
    try {
      const up = await fetch("https://image.tmdb.org/t/p/" + rest.slice(5), { signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS) });
      const type = up.headers.get("Content-Type") || "";
      if (!up.ok || !type.startsWith("image/")) return json(up.ok ? 502 : up.status === 404 ? 404 : 502, { error: "image unavailable" }, cors);
      const buf = new Uint8Array(await up.arrayBuffer());
      if (buf.byteLength > MAX_IMG_BYTES) return json(502, { error: "image too large" }, cors);
      return new Response(buf, { headers: { ...cors, "Content-Type": type, "Cache-Control": "public, max-age=2592000, immutable" } });
    } catch (e) {
      log("relay_upstream", { kind: "img", msg: String(e).slice(0, 80) });
      return json(504, { error: "upstream timeout" }, cors);
    }
  }

  // ---- catalog API ----
  if (!rest.startsWith("/3/")) return json(404, { error: "not found" }, cors);
  const path = rest.slice(3);
  if (!PATHS.some((p) => p.test(path))) return json(404, { error: "path not allowed" }, cors);
  if (!ALLOWED_ORIGINS.includes(origin)) return json(403, { error: "not allowed" }, cors); // browser-only check, see header
  const params = new URLSearchParams();
  for (const [k, v] of url.searchParams) {
    const rule = PARAMS[k];
    if (!rule || !rule.test(v) || params.has(k)) return json(400, { error: "invalid parameter", param: k.slice(0, 40) }, cors);
    params.set(k, v);
  }
  if (path.startsWith("discover/") || path.startsWith("search/")) params.set("include_adult", "false");

  if (!(await take(await clientBucket(req, "api"), LIMITS.apiPerClient.n, LIMITS.apiPerClient.win)) ||
      !(await take("api:global", LIMITS.apiGlobal.n, LIMITS.apiGlobal.win))) {
    log("relay_limit", { kind: "api", path: path.replace(/\d+/g, "#") });
    return json(429, { error: "too many requests" }, { ...cors, "Retry-After": "300" });
  }

  const ckey = path + "?" + [...params].sort().map(([k, v]) => k + "=" + v).join("&");
  const hit = cache.get(ckey);
  if (hit && Date.now() - hit.at < CACHE_MS) {
    return new Response(hit.body, { headers: { ...cors, "Content-Type": hit.type, "Cache-Control": "public, max-age=600", "X-Relay-Cache": "hit" } });
  }

  const key = Deno.env.get("TMDB_KEY") || "";
  if (!key) return json(503, { error: "relay not configured" }, cors);
  const target = new URL("https://api.themoviedb.org/3/" + path);
  for (const [k, v] of params) target.searchParams.set(k, v);
  const headers: Record<string, string> = { Accept: "application/json" };
  if (key.startsWith("eyJ")) headers.Authorization = "Bearer " + key; else target.searchParams.set("api_key", key);
  try {
    const up = await fetch(target, { headers, signal: AbortSignal.timeout(UPSTREAM_TIMEOUT_MS) });
    const len = Number(up.headers.get("Content-Length") || 0);
    if (len > MAX_API_BYTES) return json(502, { error: "response too large" }, cors);
    const buf = new Uint8Array(await up.arrayBuffer());
    if (buf.byteLength > MAX_API_BYTES) return json(502, { error: "response too large" }, cors);
    if (!up.ok) {
      log("relay_upstream", { kind: "api", status: up.status, path: path.replace(/\d+/g, "#") });
      // Never forward TMDB's error text (it can mention the key); only the status class.
      return json(up.status === 404 ? 404 : up.status === 429 ? 429 : 502, { error: up.status === 404 ? "not found" : "upstream error" }, cors);
    }
    const type = "application/json";
    if (cache.size > 300) cache.clear();
    cache.set(ckey, { at: Date.now(), body: buf, type });
    return new Response(buf, { headers: { ...cors, "Content-Type": type, "Cache-Control": "public, max-age=600" } });
  } catch (e) {
    log("relay_upstream", { kind: "api", msg: String(e).slice(0, 80), path: path.replace(/\d+/g, "#") });
    return json(504, { error: "upstream timeout" }, cors);
  }
});
