const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function page(count = 1) {
  const parties = Array.from({ length: count }, (_, i) => ({
    request_id: `request-${i}`, user_id: `user-${i}`, section: 'C', party_size: 4,
    queue_number: i + 1, status: 'RESERVED', last_batch_id: 'batch-1',
    allocation: { hold_id: `hold-${i}`, hold_expiry: '2020-01-01T00:00:00Z' },
  }));
  const state = { parties, checkouts: parties.map(party => ({
    request_id: party.request_id, hold_id: party.allocation.hold_id,
    booking_status: 'active', source: 'seat-store', cached: false,
  })), checkoutCalls: 0, activeCalls: 0, peakCalls: 0, offline: false };
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, { innerHTML: '', addEventListener() {} });
    return elements.get(id);
  };
  const context = vm.createContext({
    console, Map, Set, Promise, Array, Math, encodeURIComponent,
    document: { getElementById: element },
    getCurrentUser: () => null, onTabOpen() {}, setInterval() {}, clearInterval() {}, setTimeout() {},
    api: async endpoint => {
      if (endpoint === 'waiting-room/status') return { sale_state: 'sale_started', waiting_count: count, latecomer_count: 0, queued_count: 0 };
      if (endpoint === 'waiting-room/queue') return { count: parties.length, requests: parties };
      if (endpoint === 'dispatcher/status') return { batch_state: 'IDLE', batch_size: 10, batch_history: [{ batch_id: 'batch-1' }] };
      if (/^waiting-room\/requests\/request-\d+\/checkout$/.test(endpoint)) {
        state.checkoutCalls++;
        state.activeCalls++;
        state.peakCalls = Math.max(state.peakCalls, state.activeCalls);
        await new Promise(resolve => setImmediate(resolve));
        state.activeCalls--;
        if (state.offline) throw new Error('Checkout unavailable');
        return { ...state.checkouts[Number(endpoint.split('/')[2].split('-')[1])] };
      }
      throw new Error('Unexpected endpoint: ' + endpoint);
    },
  });
  const mockApi = context.api;
  for (const file of ['api.js', 'admin.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../static', file), 'utf8'), context, { filename: file });
  }
  context.api = mockApi;
  return { state, context, element };
}

test('Overview replaces stale RESERVED allocation results with current terminal booking states', async () => {
  for (const status of ['expired', 'confirmed', 'cancelled']) {
    const { state, context, element } = page();
    state.checkouts[0].booking_status = status;
    await context.loadAdmin();
    assert.ok(element('queue-table').innerHTML.includes(status.toUpperCase()), status);
    assert.ok(!element('queue-table').innerHTML.includes('RESERVED'));
    assert.equal(state.parties[0].status, 'RESERVED', 'Rendering must not rewrite the queue allocation result');
  }
});

test('Overview polling observes expiry and caches only verified terminal outcomes', async () => {
  const { state, context, element } = page();
  await context.loadAdmin();
  assert.ok(element('queue-table').innerHTML.includes('RESERVED'));
  state.checkouts[0].booking_status = 'expired';
  await context.loadAdmin();
  assert.ok(element('queue-table').innerHTML.includes('EXPIRED'));
  assert.equal(state.checkoutCalls, 2);
  await context.loadAdmin();
  assert.equal(state.checkoutCalls, 2, 'Ended bookings should not be polled indefinitely');
});

test('Overview marks an unverifiable booking unknown and retries after recovery', async () => {
  const { state, context, element } = page();
  state.offline = true;
  await context.loadAdmin();
  assert.ok(element('queue-table').innerHTML.includes('UNKNOWN'));
  assert.ok(!element('queue-table').innerHTML.includes('RESERVED'));
  state.offline = false;
  state.checkouts[0].booking_status = 'expired';
  await context.loadAdmin();
  assert.ok(element('queue-table').innerHTML.includes('EXPIRED'));
});

test('Overview rejects cached, mismatched and invalid checkout results', async () => {
  for (const change of [{ request_id: 'other' }, { hold_id: 'other' }, { source: 'cache' }, { cached: true }, { booking_status: 'unexpected' }]) {
    const { state, context, element } = page();
    Object.assign(state.checkouts[0], { booking_status: 'expired' }, change);
    await context.loadAdmin();
    assert.ok(element('queue-table').innerHTML.includes('UNKNOWN'), JSON.stringify(change));
  }
});

test('Overview leaves unavailable parties unchanged without requesting a checkout', async () => {
  const { state, context, element } = page();
  state.parties[0].status = 'UNAVAILABLE';
  state.parties[0].allocation = null;
  await context.loadAdmin();
  assert.ok(element('queue-table').innerHTML.includes('UNAVAILABLE'));
  assert.equal(state.checkoutCalls, 0);
});

test('Overview bounds checkout concurrency and shares overlapping refreshes', async () => {
  const { state, context } = page(12);
  await Promise.all([context.loadAdmin(), context.loadAdmin(), context.loadAdmin()]);
  assert.equal(state.checkoutCalls, 12);
  assert.ok(state.peakCalls <= 4);
});
