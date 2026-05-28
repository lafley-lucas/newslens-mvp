// newslens — minimal PWA service worker
// 정적 자산만 cache-first, API 요청은 항상 네트워크.

const CACHE = "newslens-static-v1";
const STATIC_ASSETS = [
  "./",
  "./index.html",
  "./analyze.html",
  "./style.css",
  "./app.js",
  "./icon.svg",
  "./manifest.json",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(STATIC_ASSETS)).catch(() => {})
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);

  // API 호출은 캐시 우회 (항상 네트워크)
  if (url.pathname.startsWith("/api/")) return;

  // 같은 origin 정적 자산만 cache-first
  if (url.origin !== self.location.origin) return;

  event.respondWith(
    caches.match(req).then((cached) => {
      if (cached) return cached;
      return fetch(req).then((resp) => {
        // 성공적인 응답만 캐시 (basic, opaque 등은 보수적으로 처리)
        if (resp && resp.status === 200 && resp.type === "basic") {
          const clone = resp.clone();
          caches.open(CACHE).then((cache) => cache.put(req, clone)).catch(() => {});
        }
        return resp;
      }).catch(() => cached);
    })
  );
});
