const DATA_URL = 'data/incidents.json';
const HALIFAX_TZ = 'America/Halifax';
const DOWNTOWN_CENTER = [44.6488, -63.5752];
const DOWNTOWN_RADIUS_KM = 2.2;
const downtownWords = [
  'DOWNTOWN','BARRINGTON','ARGYLE','GRANVILLE','HOLLIS','LOWER WATER','WATER ST','SPRING GARDEN',
  'SACKVILLE','DUKE','GEORGE','BRUNSWICK','GOTTINGEN','ROBIE','QUINPOOL','COGSWELL','UNIVERSITY',
  'SOUTH PARK','MORRIS','INGLIS','YOUNG AVE','WATERFRONT','SCOTIA SQUARE','PURDY'
];

const state = {
  payload:null, category:'ALL', downtownOnly:true, hideCommunity:false, hours:12, minPriority:0,
  search:'', sort:'priority', map:null, layer:null,
};

const el = id => document.getElementById(id);
const esc = (value='') => String(value).replace(/[&<>'"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
const rows = () => state.payload?.events?.length ? state.payload.events : (state.payload?.incidents || []);
function parseDate(value){const d=new Date(value);return Number.isNaN(+d)?null:d;}
function minutesAgo(value){const d=parseDate(value);return d?Math.max(0,Math.round((Date.now()-d)/60000)):null;}
function ageLabel(value){const m=minutesAgo(value);if(m===null)return'unknown time';if(m<1)return'now';if(m<60)return`${m}m ago`;const h=Math.floor(m/60),rem=m%60;if(h<24)return rem?`${h}h ${rem}m ago`:`${h}h ago`;return`${Math.floor(h/24)}d ago`;}
function haversineKm(aLat,aLon,bLat,bLon){const r=6371,rad=x=>x*Math.PI/180,p1=rad(aLat),p2=rad(bLat),dp=rad(bLat-aLat),dl=rad(bLon-aLon);const h=Math.sin(dp/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dl/2)**2;return 2*r*Math.asin(Math.sqrt(h));}
function isDowntown(row){
  if(Number.isFinite(row.lat)&&Number.isFinite(row.lon))return haversineKm(row.lat,row.lon,...DOWNTOWN_CENTER)<=DOWNTOWN_RADIUS_KM;
  if(row.neighbourhood==='DOWNTOWN')return true;
  const text=`${row.location_text||''} ${row.title||''} ${row.summary||''}`.toUpperCase();
  return downtownWords.some(w=>text.includes(w));
}
function sourceEvidence(row){return row.evidence?.length?row.evidence:[{source:row.source,source_url:row.source_url,source_class:row.source_class||row.source_kind,reported_at:row.reported_at,title:row.title}];}
function allCommunity(row){const evidence=sourceEvidence(row);return evidence.length>0&&evidence.every(e=>e.source_class==='community'||e.source_class==='secondary');}
function visibleRows(){
  const q=state.search.trim().toLowerCase();
  const out=rows().filter(row=>{
    if(state.category!=='ALL'&&row.category!==state.category)return false;
    if(state.downtownOnly&&!isDowntown(row))return false;
    if(state.hideCommunity&&allCommunity(row))return false;
    if((row.priority_score||0)<state.minPriority)return false;
    const age=minutesAgo(row.reported_at);if(age===null||age>state.hours*60)return false;
    if(q){const hay=`${row.title||''} ${row.summary||''} ${row.location_text||''} ${row.neighbourhood||''} ${(row.metadata?.source_names||[]).join(' ')}`.toLowerCase();if(!hay.includes(q))return false;}
    return true;
  });
  out.sort((a,b)=>state.sort==='newest'?(new Date(b.reported_at)-new Date(a.reported_at)):((b.priority_score||0)-(a.priority_score||0)||new Date(b.reported_at)-new Date(a.reported_at)));
  return out;
}
function categoryLabel(row){return({FIRE:'Fire',RESCUE:'Rescue',EMS:'EMS',POLICE:'Police',TRAFFIC:'Traffic',TRANSIT:'Transit',UTILITY:'Utility',WEATHER:'Weather',EMERGENCY:'Emergency',EVENT:'Event',MARINE:'Harbour',COMMUNITY:'Other'})[row.category]||row.category;}
function eventTypeLabel(row){return String(row.event_type||'local_signal').replaceAll('_',' ').replace(/\b\w/g,c=>c.toUpperCase());}
function priorityLabel(row){return`${row.priority_band||'low'} ${row.priority_score??0}`;}
function confidenceLabel(row){
  if((row.source_count||0)>=2)return`${row.source_count} sources`;
  if(row.source_class==='first_party'||row.confidence==='official')return'First-party';
  if(row.source_class==='news'||row.confidence==='reported')return'News';
  if(row.source_class==='listing'||row.confidence==='listing')return'Listing';
  if(row.source_class==='secondary'||row.confidence==='secondary')return'Secondary';
  return'Community';
}
function renderMetrics(){
  if(!state.payload)return;
  const all=rows(), recent=all.filter(r=>(minutesAgo(r.reported_at)??99999)<=180&&isDowntown(r));
  const high=all.filter(r=>(minutesAgo(r.reported_at)??99999)<=360&&(r.priority_score||0)>=60).length;
  const health=state.payload.source_health||[], healthy=health.filter(x=>x.status==='ok').length;
  const observations=state.payload.observation_count??state.payload.incidents?.length??0;
  const events=state.payload.event_count??all.length;
  const merged=Math.max(0,observations-events);
  el('metricActive').textContent=recent.length;
  el('metricHigh').textContent=high;
  el('metricSources').textContent=health.length?`${healthy}/${health.length}`:'—';
  el('metricMerged').textContent=merged;
  el('metricActiveSub').textContent='downtown · last 3h';
  el('metricHighSub').textContent='high / critical · 6h';
  el('metricSourcesSub').textContent='collectors healthy';
  el('metricMergedSub').textContent='duplicate observations merged';
}
function renderPriority(){
  const box=el('priorityCards');if(!box||!state.payload)return;
  const top=rows().filter(r=>(minutesAgo(r.reported_at)??99999)<=360).filter(r=>isDowntown(r)||(r.priority_score||0)>=60).sort((a,b)=>(b.priority_score||0)-(a.priority_score||0)||new Date(b.reported_at)-new Date(a.reported_at)).slice(0,4);
  box.innerHTML='';
  if(!top.length){box.innerHTML='<div class="empty-siren">No elevated recent events in the current dataset.</div>';return;}
  top.forEach(row=>{const card=document.createElement('article');card.className=`priority-card band-${esc(row.priority_band||'low')}`;const reasons=(row.attention_reasons||[]).slice(0,3).map(esc).join(' · ');card.innerHTML=`<div class="priority-score"><strong>${row.priority_score||0}</strong><span>priority</span></div><div class="priority-body"><div class="priority-kicker"><span>${esc(categoryLabel(row))}</span><span>${esc(ageLabel(row.reported_at))}</span><span>${row.source_count||1} src</span></div><h3>${esc(row.title)}</h3><p>${esc(row.metadata?.response_summary||row.location_text||row.summary||'')}</p><div class="priority-meta">Seriousness ${row.seriousness_score||0}${reasons?` · ${reasons}`:''}</div></div>`;box.appendChild(card);});
}
function renderSirens(){
  const box=el('sirenCards');if(!box||!state.payload)return;
  const top=rows().filter(r=>(minutesAgo(r.reported_at)??99999)<=90&&isDowntown(r)&&(r.siren_score||0)>0).sort((a,b)=>(b.siren_score||0)-(a.siren_score||0)||new Date(b.reported_at)-new Date(a.reported_at)).slice(0,3);
  box.innerHTML='';
  if(!top.length){box.innerHTML='<div class="empty-siren">No recent downtown signal in the current data explains sirens. That is an <strong>unknown</strong>, not evidence that nothing happened.</div>';return;}
  top.forEach(row=>{const card=document.createElement('article');card.className='siren-card';card.innerHTML=`<div class="siren-score" title="Siren-likelihood heuristic">${row.siren_score}</div><small>${esc(categoryLabel(row))} · ${esc(ageLabel(row.reported_at))} · ${row.source_count||1} source${(row.source_count||1)===1?'':'s'}</small><h3>${esc(row.title)}</h3><p>${esc(row.metadata?.response_summary||row.location_text||row.summary||'')}</p>`;box.appendChild(card);});
}
function sourceMeta(row){const bits=[];bits.push(`${row.source_count||1} source${(row.source_count||1)===1?'':'s'}`);bits.push(`Seriousness ${row.seriousness_score||0}`);if(row.neighbourhood)bits.push(row.neighbourhood);if(row.impact_scope&&row.impact_scope!=='local')bits.push(row.impact_scope);return bits;}

function renderResponse(row){
  const meta=row.metadata||{}, units=meta.decoded_response||[];
  if(!units.length&&!meta.response_summary)return'';
  const chips=units.map(u=>`<span class="unit-chip ${u.certainty==='unknown'?'unknown':''}" title="${esc(u.certainty==='inferred'?'Call-sign expansion inferred from HRFE apparatus naming':u.certainty==='confirmed'?'Documented/public nomenclature':'Code not yet decoded')}"><b>${esc(u.code)}</b><span>${esc(u.label)}</span></span>`).join('');
  const unknown=meta.response_unknown_codes?.length?`<p class="unit-note">Not yet decoded: ${esc(meta.response_unknown_codes.join(', '))}</p>`:'';
  return `<div class="response-summary"><p>${esc(meta.response_summary||'')}</p>${meta.response?`<div class="raw-response">Raw response: ${esc(meta.response)}</div>`:''}<details class="unit-drawer"><summary>${units.length} response code${units.length===1?'':'s'} · decode units</summary><div class="unit-grid">${chips}</div>${unknown}</details></div>`;
}

function renderEvidence(row){
  const evidence=sourceEvidence(row);if(!evidence.length)return'';
  const items=evidence.slice(0,8).map(e=>`<a class="evidence-row" href="${esc(e.source_url||'#')}" target="_blank" rel="noopener"><span><strong>${esc(e.source||'Source')}</strong><small>${esc(e.source_class||'source')} · ${esc(ageLabel(e.reported_at))}</small></span><b>↗</b></a>`).join('');
  return`<details class="evidence-drawer"><summary>${evidence.length} source observation${evidence.length===1?'':'s'} <span>view evidence</span></summary><div>${items}</div></details>`;
}
function renderFeed(){
  const list=visibleRows();el('visibleCount').textContent=list.length;const feed=el('incidentFeed');feed.innerHTML='';
  if(!list.length){feed.innerHTML='<div class="empty-feed">No normalized events match these filters. This does not mean no incident exists; check source health and broaden the filters.</div>';renderMap(list);return;}
  const tpl=el('incidentTemplate');
  list.forEach(row=>{const node=tpl.content.firstElementChild.cloneNode(true);node.classList.add(`category-${String(row.category).toLowerCase()}`,`band-${row.priority_band||'low'}`);const badges=node.querySelector('.badges');badges.innerHTML=`<span class="badge">${esc(categoryLabel(row))}</span><span class="badge priority ${esc(row.priority_band||'low')}">${esc(priorityLabel(row))}</span><span class="badge evidence-count">${esc(confidenceLabel(row))}</span><span class="badge event-type">${esc(eventTypeLabel(row))}</span>`;node.querySelector('time').textContent=ageLabel(row.reported_at);node.querySelector('h3').textContent=row.title;node.querySelector('.incident-summary').textContent=row.metadata?.response_summary||row.summary||'';node.querySelector('.incident-location').textContent=row.location_text?`⌖ ${row.location_text}${row.location_precision?' · approximate':''}`:'';const meta=node.querySelector('.incident-meta');meta.innerHTML=sourceMeta(row).map(x=>`<span>${esc(x)}</span>`).join('');node.querySelector('.incident-response').innerHTML=renderResponse(row);node.querySelector('.incident-evidence').innerHTML=renderEvidence(row);feed.appendChild(node);});
  renderMap(list);
}
function initMap(){
  if(!window.L){el('map').innerHTML='<div class="empty-feed">Map library unavailable. Timeline still works.</div>';return;}
  state.map=L.map('map',{zoomControl:false,attributionControl:true}).setView(DOWNTOWN_CENTER,14);L.control.zoom({position:'bottomright'}).addTo(state.map);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap contributors'}).addTo(state.map);state.layer=L.layerGroup().addTo(state.map);L.circle(DOWNTOWN_CENTER,{radius:DOWNTOWN_RADIUS_KM*1000,color:'#56d3c2',weight:1,opacity:.25,fillOpacity:.015,dashArray:'4 6'}).addTo(state.map);
}
function renderMap(list){
  if(!state.map||!state.layer)return;state.layer.clearLayers();
  const colors={critical:'#ff6b62',high:'#f4bc63',elevated:'#65a8ff',moderate:'#56d3c2',low:'#8f9baa'};
  list.filter(r=>Number.isFinite(r.lat)&&Number.isFinite(r.lon)).slice(0,100).forEach(row=>{const color=colors[row.priority_band]||colors.low;const radius=5+Math.min(6,Math.round((row.priority_score||0)/20));const marker=L.circleMarker([row.lat,row.lon],{radius,color,weight:2,fillColor:color,fillOpacity:.45});marker.bindPopup(`<strong>${esc(row.title)}</strong><br><span>${esc(row.location_text||'')}</span><br><small>${esc(priorityLabel(row))} · ${row.source_count||1} source${(row.source_count||1)===1?'':'s'} · ${esc(ageLabel(row.reported_at))}</small>`);marker.addTo(state.layer);});
}
function renderHealth(){
  const health=state.payload?.source_health||[],good=health.filter(x=>x.status==='ok').length;el('sourceHealthSummary').textContent=health.length?`${good}/${health.length} healthy`:'No checks';const box=el('sourceHealth');box.innerHTML='';
  health.forEach(row=>{const div=document.createElement('div');div.className=`source-row ${row.status==='ok'?'ok':'error'}`;const details=row.status==='ok'?`${row.authority} · checked ${ageLabel(row.checked_at)}`:`${row.authority} · ${row.error||'collector error'}`;div.innerHTML=`<span class="source-dot"></span><div><div class="source-name">${esc(row.source)}</div><div class="source-sub">${esc(details)}</div></div><span class="source-count">${row.records||0}</span>`;box.appendChild(div);});if(!health.length)box.innerHTML='<div class="empty-feed">Collector has not run yet.</div>';
}
function renderFreshness(){const generated=parseDate(state.payload?.generated_at),pill=el('freshnessPill');if(!generated){pill.className='status-pill stale';pill.innerHTML='<span class="dot"></span> No live refresh yet';return;}const age=Math.max(0,Math.round((Date.now()-generated)/60000));pill.className=`status-pill ${age<=12?'fresh':age>30?'stale':''}`;pill.innerHTML=`<span class="dot"></span> ${age<=1?'Fresh now':`Updated ${age}m ago`}`;el('generatedAt').textContent=`Dataset generated ${generated.toLocaleString('en-CA',{timeZone:HALIFAX_TZ,dateStyle:'medium',timeStyle:'short'})}`;}
function renderAll(){renderFreshness();renderMetrics();renderPriority();renderSirens();renderHealth();renderFeed();}
async function loadData({cacheBust=false}={}){el('refreshButton').disabled=true;try{const url=cacheBust?`${DATA_URL}?t=${Date.now()}`:DATA_URL,res=await fetch(url,{cache:'no-store'});if(!res.ok)throw new Error(`HTTP ${res.status}`);state.payload=await res.json();renderAll();}catch(err){el('freshnessPill').className='status-pill stale';el('freshnessPill').innerHTML='<span class="dot"></span> Data unavailable';el('incidentFeed').innerHTML=`<div class="empty-feed">Could not load the generated dataset: ${esc(err.message)}</div>`;}finally{el('refreshButton').disabled=false;}}
function updateClock(){const now=new Date();el('clockTime').textContent=now.toLocaleTimeString('en-CA',{timeZone:HALIFAX_TZ,hour:'2-digit',minute:'2-digit',hour12:false});el('clockDate').textContent=now.toLocaleDateString('en-CA',{timeZone:HALIFAX_TZ,weekday:'short',month:'short',day:'numeric'});}
function wireControls(){
  document.querySelectorAll('.filter').forEach(btn=>btn.addEventListener('click',()=>{document.querySelectorAll('.filter').forEach(x=>x.classList.remove('active'));btn.classList.add('active');state.category=btn.dataset.filter;renderFeed();}));
  el('downtownOnly').addEventListener('change',e=>{state.downtownOnly=e.target.checked;renderFeed();});
  el('hideCommunity').addEventListener('change',e=>{state.hideCommunity=e.target.checked;renderFeed();});
  el('priorityRange').addEventListener('change',e=>{state.minPriority=Number(e.target.value);renderFeed();});
  el('timeRange').addEventListener('change',e=>{state.hours=Number(e.target.value);renderFeed();});
  el('sortOrder').addEventListener('change',e=>{state.sort=e.target.value;renderFeed();});
  el('feedSearch').addEventListener('input',e=>{state.search=e.target.value;renderFeed();});
  el('refreshButton').addEventListener('click',()=>loadData({cacheBust:true}));
}

initMap();wireControls();updateClock();setInterval(updateClock,30000);loadData();setInterval(()=>loadData({cacheBust:true}),120000);
if('serviceWorker'in navigator)navigator.serviceWorker.register('sw.js').catch(()=>{});
