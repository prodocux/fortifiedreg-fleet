/**
 * Service Worker for FortifiedReg Fleet PWA (v0.4.0).
 * Implements strict security-compliant caching:
 * - WHITELIST: Static application shell (HTML, CSS, JS, WebManifest, Icons, Golden Samples).
 * - FORBIDDEN: NEVER cache /v1/** API routes, JWT tokens, drafts, uploads, or AI responses.
 * - OFFLINE POLICY: Fail-closed; displays backend unavailable status when disconnected.
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
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_SHELL_ASSETS);
    }).then(() => self.skipWaiting())
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

  // STRICT RULE: All /v1/** API calls must go directly to network and NEVER be cached
  if (url.pathname.startsWith('/v1/') || url.pathname.startsWith('/docs') || url.pathname.startsWith('/openapi.json')) {
    return; // Pass through to browser network layer
  }

  // Handle static assets with Stale-While-Revalidate or Cache-First
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      if (cachedResponse) {
        // Fetch background update for static assets
        fetch(event.request).then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, networkResponse));
          }
        }).catch(() => {
          // Offline, use cached
        });
        return cachedResponse;
      }
      return fetch(event.request);
    })
  );
});
