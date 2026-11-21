// Keep this file in a dedicated embed directory. Bump the version when editing its shell.
const scope = self.registration.scope;
const prefix = 'areion-embed-shell:' + scope + ':';
const name = prefix + '1';
const index = new URL('index.html', scope).href;
const script = new URL('host.js', scope).href;
self.addEventListener('install', event => {
  event.waitUntil(caches.open(name).then(cache => cache.addAll([index, script])));
});
self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    for (const key of await caches.keys()) if (key.startsWith(prefix) && key !== name) await caches.delete(key);
    await self.clients.claim();
  })());
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  url.search = ''; url.hash = '';
  const entry = event.request.mode === 'navigate' && (url.href === scope || url.href === index);
  if (!entry && url.href !== script) return;
  event.respondWith(caches.open(name).then(async cache => (await cache.match(entry ? index : script)) || fetch(event.request)));
});
