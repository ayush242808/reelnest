// ReelNest TMDB relay — a free Cloudflare Worker that fetches TMDB from outside India,
// for networks (e.g. Jio) that block themoviedb.org. It only forwards read-only TMDB requests.
//
// Optional settings (Worker › Settings › Variables):
//   TMDB_KEY        your TMDB v3 API key or v4 read token, stored as a Secret. Then the app needs no key.
//   ALLOWED_ORIGIN  e.g. https://yourname.github.io  — only your app can use the relay.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin") || "";
    const allowed = env.ALLOWED_ORIGIN || "*";
    const cors = {
      "Access-Control-Allow-Origin": allowed === "*" ? "*" : allowed,
      "Access-Control-Allow-Headers": "Authorization, Accept",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Vary": "Origin",
    };
    if (request.method === "OPTIONS") return new Response(null, { headers: cors });
    if (request.method !== "GET") return new Response("Only GET is allowed", { status: 405, headers: cors });
    if (allowed !== "*" && origin && origin !== allowed) return new Response("Not allowed", { status: 403, headers: cors });

    let target;
    const headers = { Accept: "application/json" };
    if (url.pathname.startsWith("/3/")) {
      target = new URL("https://api.themoviedb.org" + url.pathname + url.search);
      const key = env.TMDB_KEY || "";
      if (key && !target.searchParams.has("api_key") && !request.headers.get("Authorization")) {
        if (key.startsWith("eyJ")) headers.Authorization = "Bearer " + key; else target.searchParams.set("api_key", key);
      } else if (request.headers.get("Authorization")) {
        headers.Authorization = request.headers.get("Authorization");
      }
    } else if (url.pathname.startsWith("/img/")) {
      target = new URL("https://image.tmdb.org/t/p/" + url.pathname.slice(5));
    } else {
      return new Response("ReelNest TMDB relay is running.", { headers: { ...cors, "Content-Type": "text/plain" } });
    }

    const upstream = await fetch(target, { headers, cf: { cacheTtl: url.pathname.startsWith("/img/") ? 86400 * 30 : 3600, cacheEverything: true } });
    const out = new Headers(upstream.headers);
    for (const [k, v] of Object.entries(cors)) out.set(k, v);
    return new Response(upstream.body, { status: upstream.status, headers: out });
  },
};
