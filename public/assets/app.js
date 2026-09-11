const DATA_URL = `data/incidents.json`;
const HALIFAX_TZ = 'America/Halifax';
const DOWNTOWN_CENTER = [44.6488, -63.5752];
const DOWNTOWN_RADIUS_KM = 2.2;
const downtownWords = [
  'DOWNTOWN', 'BARRINGTON', 'ARGYLE', 'GRANVILLE', 'HOLLIS', 'LOWER WATER', 'WATER ST',
  'SPRING GARDEN', 'SACKVILLE', 'DUKE', 'GEORGE', 'BRUNSWICK', 'GOTTINGEN', 'ROBIE', 'QUINPOOL',
  'COGSWELL', 'UNIVERSITY', 'SOUTH PARK', 'MORRIS', 'INGLIS', 'YOUNG AVE', 'WATERFRONT'
];

const state = {
  payload: null,
  category: 'ALL',
  downtownOnly: true,
  hideCommunity: false,
  hours: 12,
  map: null,
  layer: null,
};

const el = (id) => document.getElementById(id);
const esc = (value='') => String(value).replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));

function parseDate(value) { const d = new Date(value); return Number.isNaN(+d) ? null : d; }
function minutesAgo(value) { const d = parseDate(value); return d ? Math.max(0, Math.round((Date.now()-d)/60000)) : null; }
function ageLabel(value) {
  const m = minutesAgo(value);
  if (m === null) return 'unknown time';
  if (m < 1) return 'now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m/60); const rem = m % 60;
  if (h < 24) return rem ? `${h}h ${rem}m ago` : `${h}h ago`;
  return `${Math.floor(h/24)}d ago`;
}
function haversineKm(aLat,aLon,bLat,bLon) {
  const r=6371, rad=x=>x*Math.PI/180;
  const p1=rad(aLat), p2=rad(bLat), dp=rad(bLat-aLat), dl=rad(bLon-aLon);
  const h=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;
  return 2*r*Math.asin(Math.sqrt(h));
}
function isDowntown(row) {
  if (Number.isFinite(row.lat) && Number.isFinite(row.lon)) {
    return haversineKm(row.lat,row.lon,DOWNTOWN_CENTER[0],DOWNTOWN_CENTER[1]) <= DOWNTOWN_RADIUS_KM;
  }
  const text = `${row.location_text||''} ${row.title||''} ${row.summary||''}`.toUpperCase();
  return downtownWords.some(w => text.includes(w));
}
function visibleRows() {
  if (!state.payload) return [];
  return state.payload.incidents.filter(row => {
    if (state.category !== 'ALL' && row.category !== state.category) return false;
    if (state.downtownOnly && !isDowntown(row)) return false;
    if (state.hideCommunity && row.source_kind === 'community') return false;
    const age = minutesAgo(row.reported_at);
    return age !== null && age <= state.hours * 60;
  });
}
function categoryLabel(row) {
  const labels = {FIRE:'Fire',RESCUE:'Rescue',EMS:'EMS',POLICE:'Police',TRAFFIC:'Traffic',TRANSIT:'Transit',UTILITY:'Utility',WEATHER:'Weather',EMERGENCY:'Emergency',EVENT:'Event',MARINE:'Harbour',COMMUNITY:'Other'};
  return labels[row.category] || row.category;
}
function confidenceLabel(row) {
  if (row.confidence === 'corroborated') return 'Linked signals';
  if (row.confidence === 'official') return row.source_kind === 'official_archive' ? 'First-party archive' : 'First-party';
  if (row.confidence === 'reported') return 'News';
  if (row.confidence === 'secondary') return 'Secondary';
  if (row.confidence === 'listing') return 'Event listing';
  return 'Community';
}
function sourceMeta(row) {
  const bits = [esc(row.source)];
  if (row.metadata?.response) bits.push(`Units: ${esc(row.metadata.response)}`);
  if (row.related_ids?.length) bits.push(`${row.related_ids.length} related signal${row.related_ids.length===1?'':'s'}`);
  return bits;
}
function renderFeed() {
  const rows = visibleRows();
  el('visibleCount').textContent = rows.length;
  const feed = el('incidentFeed');
  feed.innerHTML = '';
  if (!rows.length) {
    feed.innerHTML = `<div class="empty-feed">No signals match these filters. This does not mean no incident exists; check source health below.</div>`;
    renderMap(rows);
    return;
  }
  const tpl = el('incidentTemplate');
  rows.forEach(row => {
    const node = tpl.content.firstElementChild.cloneNode(true);
    node.classList.add(`category-${String(row.category).toLowerCase()}`);
    const badges = node.querySelector('.badges');
    badges.innerHTML = `<span class="badge">${esc(categoryLabel(row))}</span><span class="badge ${esc(row.confidence)}">${esc(confidenceLabel(row))}</span>`;
    node.querySelector('time').textContent = ageLabel(row.reported_at);
    node.querySelector('h3').textContent = row.title;
    node.querySelector('.incident-summary').textContent = row.summary || '';
    node.querySelector('.incident-location').textContent = row.location_text ? `⌖ ${row.location_text}${row.location_precision ? ' · approximate' : ''}` : '';
    const meta = node.querySelector('.incident-meta');
    meta.innerHTML = `${sourceMeta(row).map(x=>`<span>${x}</span>`).join('')}<a href="${esc(row.source_url)}" target="_blank" rel="noopener">Source ↗</a>`;
    feed.appendChild(node);
  });
  renderMap(rows);
}
function renderSirens() {
  const box = el('sirenCards');
  if (!state.payload) return;
  const rows = state.payload.incidents
    .filter(r => minutesAgo(r.reported_at) !== null && minutesAgo(r.reported_at) <= 90)
    .filter(r => isDowntown(r))
    .filter(r => (r.siren_score||0) > 0)
    .sort((a,b) => (b.siren_score||0)-(a.siren_score||0) || new Date(b.reported_at)-new Date(a.reported_at))
    .slice(0,3);
  box.innerHTML = '';
  if (!rows.length) {
    box.innerHTML = `<div class="empty-siren">No recent downtown dispatch signal in the current data explains sirens. That is an <strong>unknown</strong>, not evidence that nothing happened.</div>`;
    return;
  }
  rows.forEach(row => {
    const card = document.createElement('article');
    card.className = 'siren-card';
    card.innerHTML = `<div class="siren-score" title="Heuristic siren-likelihood score">${row.siren_score}</div><small>${esc(categoryLabel(row))} · ${esc(ageLabel(row.reported_at))}</small><h3>${esc(row.title)}</h3><p>${esc(row.location_text || row.summary || '')}</p>`;
    box.appendChild(card);
  });
}
function initMap() {
  if (!window.L) {
    el('map').innerHTML = '<div class="empty-feed">Map library unavailable. Timeline still works.</div>';
    return;
  }
  state.map = L.map('map', {zoomControl:false, attributionControl:true}).setView(DOWNTOWN_CENTER, 14);
  L.control.zoom({position:'bottomright'}).addTo(state.map);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom:19, attribution:'© OpenStreetMap contributors' }).addTo(state.map);
  state.layer = L.layerGroup().addTo(state.map);
  L.circle(DOWNTOWN_CENTER, {radius:DOWNTOWN_RADIUS_KM*1000, color:'#56d3c2', weight:1, opacity:.25, fillOpacity:.015, dashArray:'4 6'}).addTo(state.map);
}
function renderMap(rows) {
  if (!state.map || !state.layer) return;
  state.layer.clearLayers();
  rows.filter(r => Number.isFinite(r.lat) && Number.isFinite(r.lon)).slice(0,80).forEach(row => {
    const community = ['community','secondary'].includes(row.source_kind);
    const marker = L.circleMarker([row.lat,row.lon], {radius:7, color:community?'#b79cff':'#65a8ff', weight:2, fillColor:community?'#b79cff':'#65a8ff', fillOpacity:.45});
    marker.bindPopup(`<strong>${esc(row.title)}</strong><br><span>${esc(row.location_text||'')}</span><br><small>${esc(row.source)} · ${esc(ageLabel(row.reported_at))}</small>`);
    marker.addTo(state.layer);
  });
}
function renderHealth() {
  const rows = state.payload?.source_health || [];
  const good = rows.filter(x=>x.status==='ok').length;
  el('sourceHealthSummary').textContent = rows.length ? `${good}/${rows.length} healthy` : 'No checks';
  const box = el('sourceHealth'); box.innerHTML='';
  rows.forEach(row => {
    const div = document.createElement('div');
    div.className = `source-row ${row.status==='ok'?'ok':'error'}`;
    const details = row.status === 'ok' ? `${row.authority} · checked ${ageLabel(row.checked_at)}` : `${row.authority} · ${row.error || 'collector error'}`;
    div.innerHTML = `<span class="source-dot"></span><div><div class="source-name">${esc(row.source)}</div><div class="source-sub">${esc(details)}</div></div><span class="source-count">${row.records||0}</span>`;
    box.appendChild(div);
  });
  if (!rows.length) box.innerHTML='<div class="empty-feed">Collector has not run yet.</div>';
}
function renderFreshness() {
  const generated = parseDate(state.payload?.generated_at);
  const pill = el('freshnessPill');
  if (!generated) { pill.className='status-pill stale'; pill.innerHTML='<span class="dot"></span> No live refresh yet'; return; }
  const age = Math.max(0, Math.round((Date.now()-generated)/60000));
  pill.className = `status-pill ${age <= 12 ? 'fresh' : age > 30 ? 'stale' : ''}`;
  pill.innerHTML = `<span class="dot"></span> ${age <= 1 ? 'Fresh now' : `Updated ${age}m ago`}`;
  el('generatedAt').textContent = `Dataset generated ${generated.toLocaleString('en-CA',{timeZone:HALIFAX_TZ,dateStyle:'medium',timeStyle:'short'})}`;
}
async function loadData({cacheBust=false}={}) {
  el('refreshButton').disabled = true;
  try {
    const url = cacheBust ? `${DATA_URL}?t=${Date.now()}` : DATA_URL;
    const res = await fetch(url, {cache:'no-store'});
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    state.payload = await res.json();
    renderFreshness(); renderSirens(); renderHealth(); renderFeed();
  } catch (err) {
    el('freshnessPill').className='status-pill stale';
    el('freshnessPill').innerHTML='<span class="dot"></span> Data unavailable';
    el('incidentFeed').innerHTML=`<div class="empty-feed">Could not load the generated incident dataset: ${esc(err.message)}</div>`;
  } finally { el('refreshButton').disabled=false; }
}
function updateClock() {
  const now = new Date();
  el('clockTime').textContent = now.toLocaleTimeString('en-CA',{timeZone:HALIFAX_TZ,hour:'2-digit',minute:'2-digit',hour12:false});
  el('clockDate').textContent = now.toLocaleDateString('en-CA',{timeZone:HALIFAX_TZ,weekday:'short',month:'short',day:'numeric'});
}
function wireControls() {
  document.querySelectorAll('.filter').forEach(btn=>btn.addEventListener('click',()=>{
    document.querySelectorAll('.filter').forEach(x=>x.classList.remove('active')); btn.classList.add('active'); state.category=btn.dataset.filter; renderFeed();
  }));
  el('downtownOnly').addEventListener('change',e=>{state.downtownOnly=e.target.checked;renderFeed();});
  el('hideCommunity').addEventListener('change',e=>{state.hideCommunity=e.target.checked;renderFeed();});
  el('timeRange').addEventListener('change',e=>{state.hours=Number(e.target.value);renderFeed();});
  el('refreshButton').addEventListener('click',()=>loadData({cacheBust:true}));
}

initMap(); wireControls(); updateClock(); setInterval(updateClock,30000); loadData(); setInterval(()=>loadData({cacheBust:true}), 120000);
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(()=>{});
