const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../public/assets/app.js'), 'utf8');
function harness(fetch, { realRender = false } = {}) {
  const elements = new Map(), timers = new Map();
  let nextTimer = 1;
  const getElement = id => {
    if (!elements.has(id)) elements.set(id, {
      innerHTML: '', textContent: '', className: '', disabled: false,
      classList: { add() {}, remove() {}, toggle() {} }, attributes: {},
      setAttribute(key, value) { this.attributes[key] = value; },
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    document: { getElementById: getElement }, fetch, AbortController, console,
    setTimeout(fn, delay) { const id = nextTimer++; timers.set(id, { fn, delay }); return id; },
    clearTimeout(id) { timers.delete(id); },
  });
  // Execute the actual app functions, excluding only browser startup and dependencies.
  vm.runInContext(source.slice(0, source.indexOf('initMap();wireControls();')), context);
  if (!realRender) vm.runInContext(`renderAll = function() {
    renderFreshness(); renderMetrics();
    el('incidentFeed').innerHTML = state.payload.generated_at;
    el('map').innerHTML = state.payload.generated_at;
  };`, context);
  return {
    el: getElement, timers,
    run: code => vm.runInContext(code, context),
    load: options => context.loadData(options),
    get payload() { return vm.runInContext('state.payload', context); },
  };
}
const dataset = (age = 0) => ({ generated_at: new Date(Date.now() - age * 60000).toISOString(), events: [], incidents: [], source_health: [] });
const response = payload => ({ ok: true, json: async () => payload });

test('manual check of an unchanged stale dataset never reports green freshness', async () => {
  const payload = dataset(90), app = harness(async () => response(payload));
  await app.load();
  await app.load({ userInitiated: true });
  assert.match(app.el('freshnessPill').className, /stale/);
  assert.match(app.el('freshnessPill').innerHTML, /no newer data/);
  assert.match(app.el('generatedAt').textContent, /Dataset generated/);
});

test('background failure preserves feed, map and metrics and stays visible', async () => {
  let fail = false;
  const app = harness(async () => { if (fail) throw Error('Offline'); return response(dataset()); });
  await app.load();
  const feed = app.el('incidentFeed').innerHTML, map = app.el('map').innerHTML, metric = app.el('metricActive').textContent;
  fail = true;
  await app.load();
  assert.equal(app.el('incidentFeed').innerHTML, feed);
  assert.equal(app.el('map').innerHTML, map);
  assert.equal(app.el('metricActive').textContent, metric);
  app.run('renderFreshness()');
  assert.match(app.el('freshnessPill').innerHTML, /Refresh failed.*saved data/);
  assert.equal(app.el('refreshButton').disabled, false);
});

test('overlapping auto/manual refreshes share one in-flight owner', async () => {
  let resolve, calls = 0;
  const app = harness(() => { calls++; return new Promise(done => { resolve = done; }); });
  const first = app.load({ userInitiated: true });
  await app.load();
  await app.load({ userInitiated: true });
  assert.equal(calls, 1);
  assert.equal(app.el('refreshButton').disabled, true);
  resolve(response(dataset()));
  await first;
  assert.equal(app.el('refreshButton').disabled, false);
  assert.equal(app.el('refreshButton').attributes['aria-busy'], 'false');
});

test('invalid and older publications cannot replace a good snapshot', async () => {
  let payload = dataset();
  const app = harness(async () => response(payload));
  await app.load();
  const good = app.payload;
  for (const invalid of [null, {}, { ...good, generated_at: null }, { ...good, events: [null] },
    { ...good, source_health: {} }, { ...good, events: [{ title: 'A', category: 'FIRE', reported_at: good.generated_at, evidence: {} }] }, dataset(60)]) {
    payload = invalid;
    await app.load();
    assert.equal(app.payload, good);
    assert.match(app.el('freshnessPill').className, /stale/);
  }
});

test('initial failure is explicit and a later valid empty publication recovers', async () => {
  let payload = {};
  const app = harness(async () => response(payload));
  await app.load({ userInitiated: true });
  assert.match(app.el('incidentFeed').innerHTML, /Could not load/);
  assert.match(app.el('freshnessPill').innerHTML, /Data unavailable/);
  payload = dataset();
  await app.load();
  assert.match(app.el('freshnessPill').className, /fresh/);
  assert.equal(app.payload, payload);
  assert.equal(app.timers.size, 0);
});

test('hung requests abort after 15 seconds and unlock retry', async () => {
  const app = harness((url, { signal }) => new Promise((resolve, reject) => {
    signal.addEventListener('abort', () => reject(Error('Aborted')));
  }));
  const request = app.load();
  const timeout = [...app.timers.values()].find(timer => timer.delay === 15000);
  assert.ok(timeout);
  timeout.fn();
  await request;
  assert.equal(app.el('refreshButton').disabled, false);
  assert.equal(app.run('state.loading'), false);
  assert.match(app.el('freshnessPill').innerHTML, /Data unavailable/);
});

test('checked-in publication satisfies client validation', () => {
  const app = harness();
  const payload = fs.readFileSync(path.join(__dirname, '../public/data/incidents.json'), 'utf8');
  assert.doesNotThrow(() => app.run(`validatePayload(${payload})`));
});


test('future publication is rejected without blocking a subsequent current snapshot', async () => {
  let payload = dataset(-60);
  const app = harness(async () => response(payload), { realRender: true });
  await app.load();
  assert.equal(app.payload, null);
  assert.match(app.el('incidentFeed').innerHTML, /timestamp is in the future/);
  payload = dataset();
  await app.load();
  assert.equal(app.payload, payload);
  // A little clock skew is valid, but more than five minutes is not.
  assert.doesNotThrow(() => app.run(`validatePayload(${JSON.stringify(dataset(-4))})`));
  assert.throws(() => app.run(`validatePayload(${JSON.stringify(dataset(-6))})`), /future/);
});

test('actual render failure restores every panel from the last good snapshot', async () => {
  let payload = dataset(1);
  const app = harness(async () => response(payload), { realRender: true });
  await app.load();
  const good = app.payload, feed = app.el('incidentFeed').innerHTML;
  // Inject a deterministic DOM failure after metrics changed; ordinary health
  // rendering no longer requires createElement.
  app.run('const originalHealth = renderHealth; renderHealth = function(){if(state.payload.source_health.length)throw Error("DOM failure");originalHealth();}');
  payload = { ...dataset(), observation_count: 19, source_health: [{ status: 'ok' }] };
  await app.load();
  assert.equal(app.payload, good);
  assert.equal(app.el('metricMerged').textContent, 0);
  assert.equal(app.el('metricSources').textContent, '—');
  assert.equal(app.el('incidentFeed').innerHTML, feed);
  assert.equal(app.el('sourceHealthSummary').textContent, 'No checks');
  assert.match(app.el('freshnessPill').innerHTML, /Refresh failed.*saved data/);
});

test('initial rendering failure clears partial panels and permits recovery', async () => {
  let payload = { ...dataset(), observation_count: 19, source_health: [{ status: 'ok' }] };
  const app = harness(async () => response(payload), { realRender: true });
  app.run('const originalHealth = renderHealth; renderHealth = function(){if(state.payload.source_health.length)throw Error("DOM failure");originalHealth();}');
  app.run('state.layer = { clearLayers() { el("map").innerHTML = "cleared"; } }');
  await app.load({ userInitiated: true });
  assert.equal(app.payload, null);
  assert.equal(app.el('metricMerged').textContent, '—');
  assert.equal(app.el('sourceHealthSummary').textContent, 'Unavailable');
  assert.equal(app.el('priorityCards').innerHTML, '');
  assert.equal(app.el('map').innerHTML, 'cleared');
  assert.match(app.el('incidentFeed').innerHTML, /Could not load/);
  assert.match(app.el('freshnessPill').innerHTML, /Data unavailable/);
  assert.equal(app.el('refreshButton').disabled, false);
  payload = dataset();
  await app.load();
  assert.equal(app.payload, payload);
  assert.match(app.el('incidentFeed').innerHTML, /No normalized events/);
});

test('downtown fallback distinguishes Sackville Street from Sackville communities', () => {
  const app = harness(async () => response(dataset()));
  for (const location of ['Lynnville Drive, Lower Sackville', 'Middle Sackville', 'Upper Sackville', 'Sackville Drive', 'Sackville', 'Sackville Drive, Halifax']) {
    assert.equal(app.run(`isDowntown({location_text:${JSON.stringify(location)}})`), false, location);
  }
  for (const location of ['SACKVILLE ST, HALIFAX', 'Sackville Street, Halifax']) {
    assert.equal(app.run(`isDowntown({location_text:${JSON.stringify(location)}})`), true, location);
  }
});

test('coverage separates recent publication from partial source coverage', () => {
  const app=harness(async()=>response(dataset()));
  const result=app.run(`coverageSummary({generated_at:new Date().toISOString(),source_health:[{status:'ok',checked_at:new Date().toISOString()},{status:'error',checked_at:new Date().toISOString()}]},null)`);
  assert.equal(result.status,'partial');assert.match(result.detail,/1\/2 collectors/);assert.match(result.detail,/1 failed or unknown/);
});
test('old and missing checks never imply live source health', () => {
 const app=harness(async()=>response(dataset()));
 const result=app.run(`coverageSummary({generated_at:new Date().toISOString(),source_health:[{status:'ok'},{status:'ok',checked_at:new Date(Date.now()-3600000).toISOString()}]},null)`);
 assert.equal(result.status,'partial');assert.match(result.detail,/2 checks are old or undated/);
});
test('failed refresh and old publication are prominent coverage warnings', async () => {
 const app=harness(async()=>response(dataset(45)));await app.load();
 assert.match(app.el('coverageTitle').textContent,/delayed/);
 app.run(`state.loadError='offline';renderFreshness()`);
 assert.match(app.el('coverageTitle').textContent,/Refresh failed/);assert.match(app.el('coverageDetail').textContent,/not the source feeds/);
});
test('empty coverage and future clocks remain unknown or warning', () => {
 const app=harness(async()=>response(dataset()));
 assert.match(app.run(`coverageSummary(null,null).detail`),/coverage is unknown/);
 assert.equal(app.run(`coverageSummary({generated_at:new Date().toISOString(),source_health:[]},null).status`),'partial');
 assert.equal(app.run(`coverageSummary({generated_at:new Date(Date.now()+60000).toISOString()},null).status`),'warning');
});
test('reset filters restores consistent state and controls', () => {
 const app=harness(async()=>response(dataset()));
 app.run(`document.querySelectorAll=()=>[];renderFeed=()=>{};Object.assign(state,{category:'POLICE',downtownOnly:false,hideCommunity:true,hours:48,minPriority:60,search:'abc',sort:'newest'});resetFilters()`);
 assert.equal(app.run('state.category'),'ALL');assert.equal(app.run('state.hours'),12);assert.equal(app.run('state.search'),'');assert.equal(app.el('downtownOnly').checked,true);assert.equal(app.el('feedSearch').value,'');assert.equal(app.el('timeRange').value,'12');
});


test('quick views deterministically reset hidden filters without location access', () => {
 const app=harness(async()=>response(dataset()));
 app.run("document.querySelectorAll=()=>[]; renderFeed=()=>{}; state.search='old'; state.category='FIRE';state.sourceMode='first_party';applyPreset('transport')");
 assert.equal(app.run('state.transportOnly'),true);
 assert.equal(app.run('state.downtownOnly'),false);
 assert.equal(app.run('state.search'),'');
 assert.equal(app.el('timeRange').value,'24');
 app.run("applyPreset('downtown')");
 assert.equal(app.run('state.transportOnly'),false);
 assert.equal(app.run('state.hours'),3);
 assert.equal(app.run('state.downtownOnly'),true);
 app.run('resetFilters()');
 assert.equal(app.run('state.sourceMode'),'all');
 assert.equal(app.run('state.compact'),false);
});
test('transport and evidence filters are explicit independent predicates',()=>{
 const app=harness(async()=>response(dataset()));
 app.run(`state.downtownOnly=false;state.payload={events:[
 {title:'Traffic',category:'TRAFFIC',reported_at:new Date().toISOString(),evidence:[{source_class:'first_party'}]},
 {title:'Bus',category:'TRANSIT',reported_at:new Date().toISOString(),evidence:[{source_class:'community'}]},
 {title:'Fire',category:'FIRE',reported_at:new Date().toISOString(),evidence:[{source_class:'first_party'}]}
 ]};state.transportOnly=true`);
 assert.equal(app.run('visibleRows().length'),2);
 app.run("state.sourceMode='first_party'");assert.equal(app.run('visibleRows().length'),1);
 app.run("state.sourceMode='noncommunity'");assert.equal(app.run('visibleRows()[0].title'),'Traffic');
});
test('map reports unmapped coverage even without a map library',()=>{
 const app=harness(async()=>response(dataset()));
 app.run('renderMap([{lat:44.6,lon:-63.5},{title:"unlocated"}])');
 assert.match(app.el('mapCoverage').textContent,/1 of 2 filtered reports/);
 assert.match(app.el('mapCoverage').textContent,/Unmapped reports remain/);
});

test('collector health prioritizes failures and keeps successful timestamps expandable',()=>{
 const app=harness(async()=>response(dataset()));
 app.run(`state.payload={source_health:[{source:'Good',status:'ok',checked_at:new Date().toISOString()},{source:'Bad',status:'error',error:'failed'}]};renderHealth()`);
 const html=app.el('sourceHealth').innerHTML;
 assert.ok(html.indexOf('Bad')<html.indexOf('Good'));
 assert.match(html,/<details class="healthy-drawer">/);
 assert.match(html,/1 collectors need attention/);
});
