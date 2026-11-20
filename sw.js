// ReelNest offline cache: the app shell works offline; TMDB requests always go to the network.
const CACHE = "reelnest-v15";
const SHELL = ["./", "./index.html", "./config.js", "./manifest.webmanifest", "./icon.svg", "./icon-192.png", "./icon-512.png"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener("activate", (e) => e.waitUntil(
  caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim())));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.hostname.endsWith(".supabase.co") || url.hostname === "api.themoviedb.org" || url.hostname === "api.tmdb.org" || url.pathname.startsWith("/3/")) return;
  if (url.origin === location.origin) {
    // Network first for the page so updates arrive; cached copy when offline.
    // "no-cache" revalidates with GitHub Pages every time, so updates (including config.js) show up on the next load.
    e.respondWith(fetch(e.request, { cache: "no-cache" }).then((r) => { const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return r; })
      .catch(() => caches.match(e.request, { ignoreSearch: true }).then((r) => r || caches.match("./index.html"))));
    return;
  }
  if (url.hostname === "image.tmdb.org" || url.hostname === "media.themoviedb.org" || url.hostname === "wsrv.nl" || url.hostname === "images.weserv.nl" || url.pathname.startsWith("/img/") || url.hostname.endsWith("gstatic.com") || url.hostname === "fonts.googleapis.com") {
    e.respondWith(caches.match(e.request).then((hit) => hit || fetch(e.request).then((r) => {
      const copy = r.clone(); caches.open(CACHE).then((c) => c.put(e.request, copy)); return r; })));
  }
});
