const CACHE='hfx-pulse-shell-v4';
const SHELL=['./','./index.html','./assets/styles.css','./assets/ui-fix.css','./assets/app.js','./manifest.webmanifest'];
self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(Promise.all([
  caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE&&key.startsWith('hfx-pulse-shell-')).map(key=>caches.delete(key)))),
  self.clients.claim()
])));
self.addEventListener('fetch',e=>{
  const u=new URL(e.request.url);
  if (u.pathname.endsWith('/data/incidents.json')) return;
  if (e.request.method!=='GET') return;
  e.respondWith(fetch(e.request).then(r=>{const copy=r.clone();caches.open(CACHE).then(c=>c.put(e.request,copy));return r;}).catch(()=>caches.match(e.request)));
});
