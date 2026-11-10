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
      classList: { add() {}, remove() {} }, attributes: {},
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
  // Real renderMetrics updates the count before real renderHealth attempts a DOM
  // operation unavailable in this test document. This simulates a partial render.
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
