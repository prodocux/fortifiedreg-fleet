/**
 * Service Worker for FortifiedReg Fleet PWA (v0.4.0).
 * Implements strict security-compliant caching:
 * - WHITELIST: Static application shell only.
 * - FORBIDDEN: NEVER cache /v1/** API routes, JWT tokens, drafts, uploads, or AI responses.
 * - STRATEGY: Network-First for allowlisted shell assets with offline fallback; flushes stale caches on activate.
 */

const CACHE_NAME = 'fortifiedreg-fleet-shell-v0.4.0';

const STATIC_SHELL_ASSETS = [
  '/',
  '/static/portal.css?v=0.4.0',
  '/static/portal.js?v=0.4.0',
  '/static/manifest.webmanifest',
  '/static/samples.json',
  '/static/icons/icon-192.svg',
  '/static/icons/icon-512.svg'
];

self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_SHELL_ASSETS);
    })
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // STRICT RULE: Only GET requests for exact STATIC_SHELL_ASSETS allowlist may interact with cache
  const isAllowlisted = STATIC_SHELL_ASSETS.some((asset) => {
    return url.pathname === asset || (url.pathname + url.search) === asset;
  });

  if (event.request.method !== 'GET' || !isAllowlisted) {
    return; // Pass directly to browser network layer without caching
  }

  // Network-First Strategy for Application Shell
  event.respondWith(
    fetch(event.request)
      .then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200) {
          const resClone = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, resClone));
        }
        return networkResponse;
      })
      .catch(() => {
        return caches.match(event.request);
      })
  );
});
