// Offline cache for the hosted build. Not registered inside the Android app,
// whose files are already on the device.
//
// The build tool stamps BUILD below with a hash over every other file, so a
// new deploy is a byte-different worker and the browser installs it; the old
// cache is dropped on activation. Cache-first for everything the build lists,
// because a 14 MB interpreter should download once, not per visit.

const BUILD = "__BUILD__";
const CACHE = `vibecoder-${BUILD}`;

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const info = await (await fetch("build-info.json", { cache: "no-store" })).json();
    const cache = await caches.open(CACHE);
    await cache.addAll(["./", ...Object.keys(info.files).filter((name) => name !== "sw.js")]);
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    for (const name of await caches.keys()) {
      if (name.startsWith("vibecoder-") && name !== CACHE) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET" || new URL(request.url).origin !== location.origin) return;
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const hit = await cache.match(request, { ignoreSearch: true })
      || (request.mode === "navigate" ? await cache.match("./") : undefined);
    return hit || fetch(request);
  })());
});
