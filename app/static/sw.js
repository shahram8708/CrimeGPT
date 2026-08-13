const CACHE_VERSION = "crimegpt-shell-v3";
const PRECACHE = [
  "/",
  "/offline",
  "/about",
  "/how-it-works",
  "/features",
  "/disclaimer",
  "/privacy",
  "/terms",
  "/contact",
  "/static/css/app.css",
  "/static/js/app.js",
  "/static/js/pwa.js",
  "/static/vendor/bootstrap/bootstrap.min.css",
  "/static/vendor/bootstrap/bootstrap.bundle.min.js",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/i18n/en.json",
  "/static/i18n/hi.json",
  "/static/i18n/gu.json",
  "/manifest.webmanifest"
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_VERSION).then(function (cache) {
      return cache.addAll(PRECACHE).catch(function () {});
    })
  );
  self.skipWaiting();
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(
        keys.filter(function (k) { return k !== CACHE_VERSION; }).map(function (k) { return caches.delete(k); })
      );
    })
  );
  self.clients.claim();
});

function isSensitive(url) {
  var p = url.pathname;
  return (
    p.indexOf("/api/") === 0 ||
    p === "/healthz" ||
    p.indexOf("/cases") === 0 ||
    p.indexOf("/tools") === 0 ||
    p.indexOf("/results") === 0 ||
    p.indexOf("/documents") === 0 ||
    p.indexOf("/downloads") === 0 ||
    p.indexOf("/admin") === 0 ||
    p.indexOf("/jobs/") === 0 ||
    p.indexOf("/dashboard") === 0
  );
}

self.addEventListener("fetch", function (event) {
  var req = event.request;
  if (req.method !== "GET") return;
  var url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (isSensitive(url)) return;
  if (url.pathname.indexOf("/auth/") === 0) {
    return;
  }

  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).then(function (res) {
        if (res && res.ok) {
          var copy = res.clone();
          caches.open(CACHE_VERSION).then(function (cache) { cache.put(req, copy); });
        }
        return res;
      }).catch(function () {
        return caches.match(req).then(function (hit) {
          return hit || caches.match("/offline");
        });
      })
    );
    return;
  }

  event.respondWith(
    caches.match(req).then(function (hit) {
      if (hit) return hit;
      return fetch(req).then(function (res) {
        if (res && res.ok && (url.pathname.indexOf("/static/") === 0 || url.pathname === "/manifest.webmanifest")) {
          var copy = res.clone();
          caches.open(CACHE_VERSION).then(function (cache) { cache.put(req, copy); });
        }
        return res;
      }).catch(function () { return caches.match("/offline"); });
    })
  );
});
