/* Minimal service worker — caches the app shell so the PWA opens offline */
const CACHE = "smc-bot-v1";
const SHELL = [
  "/",
  "/static/styles.css",
  "/static/app.js",
  "/static/manifest.webmanifest",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(k => k !== CACHE).map(k => caches.delete(k))
  )));
  self.clients.claim();
});

self.addEventListener("fetch", (e) => {
  // Network-first for /api/*; cache-first for shell
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) {
    return; // let it pass through to the network
  }
  e.respondWith(
    caches.match(e.request).then(cached =>
      cached || fetch(e.request).then(resp => {
        if (resp && resp.status === 200 && resp.type === "basic") {
          const clone = resp.clone();
          caches.open(CACHE).then(c => c.put(e.request, clone));
        }
        return resp;
      }).catch(() => cached)
    )
  );
});
