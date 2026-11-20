// ReelNest shared TMDB relay (Supabase Edge Function "tmdb").
// Lets anyone using the ReelNest site browse the catalog without their own TMDB key, and gets
// around Indian ISPs (e.g. Jio) that block themoviedb.org. Read-only: it forwards GET requests only.
//
// Setup (Supabase dashboard):
//   Edge Functions › Secrets: TMDB_KEY = your TMDB v3 API key or v4 read token. It stays on the server.
//   Function settings: turn OFF "Verify JWT" (the site calls it without signing in).
// Catalog calls are only answered for pages served from ALLOWED_ORIGINS.

const ALLOWED_ORIGINS = ["https://ayush242808.github.io"];

Deno.serve(async (req: Request) => {
  const origin = req.headers.get("Origin") || "";
  const cors: Record<string, string> = {
    "Access-Control-Allow-Origin": ALLOWED_ORIGINS.includes(origin) ? origin : ALLOWED_ORIGINS[0],
    "Access-Control-Allow-Headers": "Authorization, Accept, apikey",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Vary": "Origin",
  };
  if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
  if (req.method !== "GET") return new Response("Only GET is allowed", { status: 405, headers: cors });

  const url = new URL(req.url);
  const at = url.pathname.indexOf("/tmdb");
  const rest = at >= 0 ? url.pathname.slice(at + 5) : url.pathname; // "/3/..." or "/img/..."
  const headers: Record<string, string> = { Accept: "application/json" };
  let target: URL;

  if (rest.startsWith("/3/")) {
    // Catalog data: only for the ReelNest site (browsers always send Origin on these cross-site fetches).
    if (!ALLOWED_ORIGINS.includes(origin)) return new Response("Not allowed", { status: 403, headers: cors });
    target = new URL("https://api.themoviedb.org" + rest + url.search);
    const own = req.headers.get("Authorization");
    if (own && own.startsWith("Bearer eyJ")) headers.Authorization = own; // a user's own TMDB v4 token, if they sent one
    if (!target.searchParams.has("api_key") && !headers.Authorization) {
      const key = Deno.env.get("TMDB_KEY") || "";
      if (!key) return new Response(JSON.stringify({ status_message: "Relay has no TMDB key configured" }), { status: 401, headers: { ...cors, "Content-Type": "application/json" } });
      if (key.startsWith("eyJ")) headers.Authorization = "Bearer " + key; else target.searchParams.set("api_key", key);
    }
  } else if (rest.startsWith("/img/") && /^\/img\/(w\d+|original)\/[\w.-]+\.(jpg|jpeg|png|svg|webp)$/.test(rest)) {
    target = new URL("https://image.tmdb.org/t/p/" + rest.slice(5));
    delete headers.Accept;
  } else {
    return new Response("ReelNest TMDB relay is running.", { headers: { ...cors, "Content-Type": "text/plain" } });
  }

  const upstream = await fetch(target, { headers });
  const out = new Headers();
  for (const h of ["Content-Type", "Content-Length", "ETag", "Last-Modified"]) { const v = upstream.headers.get(h); if (v) out.set(h, v); }
  out.set("Cache-Control", rest.startsWith("/img/") ? "public, max-age=2592000, immutable" : "public, max-age=600");
  for (const [k, v] of Object.entries(cors)) out.set(k, v);
  return new Response(upstream.body, { status: upstream.status, headers: out });
});
