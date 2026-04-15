// Service Worker — Marfil Dashboard
// Estrategias:
//  - App shell (index.html, icons): CACHE FIRST con revalidacion en background
//  - dashboard.json: NETWORK FIRST con fallback a cache (asi siempre intenta
//    traer lo mas fresco, pero funciona offline con los ultimos datos).
//
// Version: subir el numero cada vez que cambies index.html o el SW mismo
// para forzar que los usuarios bajen la nueva version.

const VERSION = 'marfil-v3';
const STATIC_CACHE = `${VERSION}-static`;
const DATA_CACHE = `${VERSION}-data`;

const APP_SHELL = [
  './',
  './index.html',
  './manifest.json',
  './assets/icon-192.png',
  './assets/icon-512.png',
  './assets/apple-touch-icon.png',
  './assets/favicon-32.png',
];

// ---------- Install: pre-cachear el app shell ----------
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => {
      return cache.addAll(APP_SHELL).catch((err) => {
        // No fallar toda la instalacion si un recurso opcional no se pudo cachear
        console.warn('[SW] Error pre-caching some assets:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

// ---------- Activate: limpiar caches viejos ----------
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))
      );
    }).then(() => self.clients.claim())
  );
});

// ---------- Fetch: router por tipo de recurso ----------
self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Solo manejar GET y same-origin
  if (req.method !== 'GET' || url.origin !== self.location.origin) {
    return;
  }

  // dashboard.json: network-first
  if (url.pathname.endsWith('/dashboard.json') || url.pathname.endsWith('dashboard.json')) {
    event.respondWith(networkFirst(req));
    return;
  }

  // Todo lo demas (HTML, CSS, JS, iconos): cache-first con revalidacion
  event.respondWith(cacheFirstWithRevalidate(req));
});

// ---------- Estrategia: network-first para datos ----------
async function networkFirst(request) {
  const cache = await caches.open(DATA_CACHE);
  try {
    const fresh = await fetch(request, { cache: 'no-store' });
    if (fresh && fresh.ok) {
      // Guardamos una copia en cache para usar si no hay red
      cache.put(request, fresh.clone());
    }
    return fresh;
  } catch (e) {
    // Sin red: devolver lo que tengamos en cache
    const cached = await cache.match(request);
    if (cached) {
      return cached;
    }
    // Si no hay nada en cache, devolvemos un json vacio valido
    return new Response(
      JSON.stringify({ offline: true, daily: {}, updated_at: null }),
      { headers: { 'Content-Type': 'application/json' } }
    );
  }
}

// ---------- Estrategia: cache-first con revalidacion en background ----------
async function cacheFirstWithRevalidate(request) {
  const cache = await caches.open(STATIC_CACHE);
  const cached = await cache.match(request);

  // Background revalidation: en paralelo, intentamos actualizar el cache
  // para la proxima visita, pero sin bloquear la respuesta actual.
  const fetchPromise = fetch(request).then((response) => {
    if (response && response.ok) {
      cache.put(request, response.clone());
    }
    return response;
  }).catch(() => null);

  // Si ya tenemos el recurso cacheado, lo devolvemos YA
  if (cached) {
    return cached;
  }

  // Si no, esperamos la red
  const fresh = await fetchPromise;
  if (fresh) return fresh;

  // Fallback: si es una navegacion HTML, servir el index cacheado
  if (request.mode === 'navigate') {
    const indexCached = await cache.match('./index.html');
    if (indexCached) return indexCached;
  }

  return new Response('Offline', { status: 503, statusText: 'Service Unavailable' });
}

// ---------- Mensajes: permitir refresh manual del cache de datos ----------
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
