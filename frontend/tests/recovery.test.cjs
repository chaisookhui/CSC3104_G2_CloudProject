// Run with: node --test frontend/tests/recovery.test.cjs
// Execute the shipped browser scripts in separate tab contexts with shared
// storage/locks. HTTP responses are controlled; no deployment/data is changed.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const copy = value => JSON.parse(JSON.stringify(value));
const settle = () => new Promise(resolve => setImmediate(resolve));

function world(status = 'RESERVED') {
  const user = { name: 'Alice', user_id: 'alice' };
  const expiry = new Date(Date.now() + 300000).toISOString();
  const party = { request_id: 'request-1', user_id: 'alice', section: 'A', party_size: 2,
    queue_number: 7, status, allocation: status === 'RESERVED' ? {
      hold_id: 'hold-1', hold_status: 'ACTIVE', hold_expiry: expiry, seats: ['A-1-1', 'A-1-2'],
    } : undefined };
  const checkout = { request_id: party.request_id, hold_id: 'hold-1', booking_status: 'active',
    hold_expiry: expiry, original_hold_expiry: expiry, seats: ['A-1-1', 'A-1-2'],
    payment_attempts: [], cancellation: null, can_pay: true, can_cancel: true, source: 'seat-store', cached: false };
  const storage = new Map([['currentUser', JSON.stringify(user)], ['currentRequest', JSON.stringify(party)]]);
  const lockQueue = new Map();
  const state = { user, party, checkout, storage, calls: [], offline: false,
    losePayment: false, loseRegistration: false, declineImmediately: false, registered: false };
  state.lock = (name, action) => {
    const next = (lockQueue.get(name) || Promise.resolve()).then(action);
    lockQueue.set(name, next.catch(() => {}));
    return next;
  };
  state.fetch = async (url, options = {}) => {
    const endpoint = url.replace('/api/', '');
    const body = options.body ? JSON.parse(options.body) : null;
    state.calls.push({ endpoint, body });
    if (state.offline) throw new Error('Disconnected');
    let value;
    if (endpoint === 'waiting-room/submit') {
      state.registered = true;
      value = state.party;
      if (state.loseRegistration) { state.loseRegistration = false; throw new Error('Response lost after commit'); }
    } else if (endpoint.endsWith('/checkout')) {
      if (state.checkoutOffline) throw new Error('Checkout unavailable');
      value = state.checkout;
    }
    else if (endpoint === 'waiting-room/requests/request-1') value = state.party;
    else if (endpoint === 'payment/payments') {
      let attempt = state.checkout.payment_attempts.find(a => a.key === body.attempt_key);
      if (!attempt) {
        attempt = { payment_id: 'payment-' + state.checkout.payment_attempts.length, key: body.attempt_key,
          outcome: body.outcome, attempt_status: body.outcome === 'decline' && state.declineImmediately ? 'declined' : 'pending' };
        state.checkout.payment_attempts.push(attempt);
      }
      state.checkout.can_pay = attempt.attempt_status !== 'pending';
      value = { payment_id: attempt.payment_id, status: attempt.attempt_status === 'declined' ? 'failed' : 'pending' };
      if (state.losePayment) { state.losePayment = false; throw new Error('Response lost after commit'); }
    } else if (endpoint === 'payment/checkouts/cancel') {
      state.checkout.booking_status = 'cancelled';
      state.checkout.can_pay = state.checkout.can_cancel = false;
      state.checkout.cancellation = { action_id: 'cancel-1', status: 'cancelled' };
      value = state.checkout.cancellation;
    } else throw new Error('Unexpected request: ' + endpoint);
    const snapshot = copy(value);
    return { ok: true, status: 200, json: async () => snapshot };
  };
  return state;
}

function tab(state, { locks = true } = {}) {
  const timers = new Map();
  const events = new Map();
  const elements = new Map();
  let nextTimer = 0;
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      id, innerHTML: '', textContent: '', hidden: false, listeners: {},
      classList: { contains: name => id === 'join' && name === 'active', toggle() {} },
      addEventListener(name, handler) { this.listeners[name] = handler; },
      querySelector(selector) {
        const buttonId = selector.slice(1);
        return this.innerHTML.includes(`id="${buttonId}"`) ? element(buttonId) : null;
      },
      closest: () => element('join'),
    });
    return elements.get(id);
  }
  const context = vm.createContext({
    console, Date, Promise, JSON, crypto: { randomUUID },
    navigator: locks ? { locks: { request: state.lock } } : {},
    localStorage: { getItem: key => state.storage.get(key) ?? null,
      setItem: (key, value) => {
        if (state.failWrites) throw new Error('Storage quota exceeded');
        state.storage.set(key, value);
      }, removeItem: key => {
        if (state.failWrites) throw new Error('Storage unavailable');
        state.storage.delete(key);
      } },
    document: { getElementById: element, querySelectorAll: () => [],
      querySelector: () => ({ dataset: { tab: 'join' } }) },
    fetch: state.fetch,
    setInterval: (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, delay }); return id; },
    clearInterval: id => timers.delete(id),
    addEventListener: (name, handler) => {
      const previous = events.get(name);
      events.set(name, previous ? event => { previous(event); handler(event); } : handler);
    },
    confirm: () => true,
  });
  context.window = context;
  for (const file of ['api.js', 'app.js', 'booking.js', 'join.js', 'checkout.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../static', file), 'utf8'), context, { filename: file });
  }
  return { context, element, timers, events,
    run: code => vm.runInContext(code, context),
    refresh: () => context.refreshBooking(state.party.request_id),
    click: id => element(id).listeners.click(),
  };
}

test('refresh restores the same queued request and position without registration', async () => {
  const state = world('QUEUED');
  for (let i = 0; i < 2; i++) {
    const page = tab(state);
    await page.refresh();
    assert.match(page.element('booking-result').innerHTML, /QUEUED/);
    assert.equal(page.run('getCurrentRequest().queue_number'), 7);
    assert.equal(page.run('getCurrentRequest().request_id'), 'request-1');
  }
  assert.ok(state.calls.every(call => call.body === null));
});

test('active hold recovers its seats/deadline and actions wait for fresh checkout', async () => {
  const state = world();
  const page = tab(state);
  page.context.renderCheckout();
  assert.match(page.element('checkout-step').innerHTML, /id="ticket-pay"[^>]*disabled/);
  await page.refresh();
  assert.equal(page.run('getCurrentCheckout().original_hold_expiry'), state.party.allocation.hold_expiry);
  assert.match(page.element('checkout-step').innerHTML, /A-1-1, A-1-2/);
  assert.doesNotMatch(page.element('checkout-step').innerHTML, /id="ticket-pay"[^>]*disabled/);
});

test('confirmed, cancelled and expired outcomes recover without saved payment IDs', async () => {
  for (const status of ['confirmed', 'cancelled', 'expired']) {
    const state = world();
    state.checkout.booking_status = status;
    state.checkout.can_pay = state.checkout.can_cancel = false;
    for (let reload = 0; reload < 2; reload++) {
      const page = tab(state);
      await page.refresh();
      assert.match(page.element('booking-result').innerHTML, new RegExp(status.toUpperCase()));
      assert.ok(!page.element('checkout-step').innerHTML.includes('id="ticket-pay"'));
      assert.match(page.element('checkout-step').innerHTML, /A-1-1, A-1-2/);
    }
    assert.ok(state.calls.every(call => call.body === null));
  }
});

test('unavailable remains terminal and does not request a checkout or new queue entry', async () => {
  const state = world('UNAVAILABLE');
  const page = tab(state);
  await page.refresh();
  assert.match(page.element('booking-result').innerHTML, /UNAVAILABLE/);
  assert.equal(page.element('checkout-step').hidden, true);
  assert.equal(state.calls.length, 1);
});

test('temporary network failure keeps polling and recovers original request', async () => {
  const state = world('QUEUED');
  state.offline = true;
  const page = tab(state);
  page.run('trackBooking("request-1")');
  await settle();
  assert.match(page.element('booking-result').innerHTML, /reconnecting automatically/);
  const poll = [...page.timers.values()].find(t => t.delay === 2000);
  assert.ok(poll);
  state.offline = false;
  await poll.callback();
  assert.match(page.element('booking-result').innerHTML, /QUEUED/);
  assert.equal(page.run('getCurrentRequest().queue_number'), 7);
});

test('payment/cancellation remain paused while checkout cannot be verified', async () => {
  const state = world();
  const page = tab(state);
  await page.refresh();
  state.offline = true;
  await page.refresh();
  assert.match(page.element('checkout-step').innerHTML, /id="ticket-pay"[^>]*disabled/);
  await page.click('ticket-pay');
  await page.click('ticket-cancel');
  assert.equal(state.calls.filter(c => c.body).length, 0);
});

test('expiry in another tab updates the open booking without any local payment ID', async () => {
  const state = world();
  const page = tab(state);
  await page.refresh();
  state.checkout.booking_status = 'expired';
  state.checkout.can_pay = state.checkout.can_cancel = false;
  await page.refresh();
  assert.match(page.element('booking-result').innerHTML, /EXPIRED/);
  assert.match(page.element('checkout-step').innerHTML, /Reservation expired/);
  assert.doesNotMatch(page.element('checkout-step').innerHTML, /id="ticket-pay"/);
  assert.equal(page.run('getCurrentRequest().allocation.hold_expiry'), state.checkout.original_hold_expiry);
});

test('checkout outages, wrong hold IDs and changed deadlines never enable payment', async () => {
  for (const problem of ['outage', 'identity', 'deadline']) {
    const state = world();
    const page = tab(state);
    if (problem === 'outage') state.checkoutOffline = true;
    if (problem === 'identity') state.checkout.hold_id = 'someone-elses-hold';
    if (problem === 'deadline') state.checkout.hold_expiry = new Date(Date.now() + 600000).toISOString();
    await page.refresh();
    assert.match(page.element('booking-result').innerHTML, /Unable to verify checkout/);
    assert.equal(page.context.isCheckoutVerified(), false);
    await page.click('ticket-pay');
    assert.ok(state.calls.every(c => c.body === null));
  }
});

test('simultaneous tabs submit one payment, including without browser locks', async () => {
  for (const locks of [true, false]) {
    const state = world();
    const left = tab(state, { locks });
    const right = tab(state, { locks });
    await Promise.all([left.refresh(), right.refresh()]);
    await Promise.all([left.click('ticket-pay'), right.click('ticket-pay')]);
    assert.equal(state.checkout.payment_attempts.length, 1);
    assert.equal(new Set(state.calls.filter(c => c.endpoint === 'payment/payments').map(c => c.body.attempt_key)).size, 1);
  }
});

test('two tabs do not turn one declined generation into two attempts', async () => {
  const state = world();
  state.declineImmediately = true;
  const left = tab(state), right = tab(state);
  await Promise.all([left.refresh(), right.refresh()]);
  await Promise.all([left.click('ticket-decline'), right.click('ticket-decline')]);
  assert.equal(state.checkout.payment_attempts.length, 1);
  await right.refresh();
  await right.click('ticket-pay');
  assert.equal(state.checkout.payment_attempts.length, 2);
  assert.equal(state.checkout.original_hold_expiry, state.party.allocation.hold_expiry);
});

test('lost payment response and reload recover the pending attempt without resubmitting', async () => {
  const state = world();
  state.losePayment = true;
  const page = tab(state);
  await page.refresh();
  await page.click('ticket-pay');
  const reloaded = tab(state);
  await reloaded.refresh();
  await reloaded.click('ticket-pay');
  assert.equal(state.calls.filter(c => c.endpoint === 'payment/payments').length, 1);
  assert.match(reloaded.element('checkout-step').innerHTML, /Payment is processing/);
});

test('concurrent cancellation recovers one stable action', async () => {
  const state = world();
  const left = tab(state), right = tab(state);
  await Promise.all([left.refresh(), right.refresh()]);
  await Promise.all([left.click('ticket-cancel'), right.click('ticket-cancel')]);
  assert.equal(state.calls.filter(c => c.endpoint === 'payment/checkouts/cancel').length, 1);
  const reloaded = tab(state);
  await reloaded.refresh();
  assert.match(reloaded.element('booking-result').innerHTML, /CANCELLED/);
});

test('lost registration response is replayed on reload with the same identity/payload', async () => {
  const state = world('QUEUED');
  state.storage.delete('currentRequest');
  state.loseRegistration = true;
  const page = tab(state);
  await page.context.submitRegistration({ user_id: 'alice', section: 'A', party_size: 2 });
  assert.equal(state.registered, true);
  const reloaded = tab(state);
  reloaded.context.renderJoin();
  await settle();
  assert.equal(reloaded.run('getCurrentRequest().request_id'), 'request-1');
  const bodies = state.calls.filter(c => c.endpoint === 'waiting-room/submit').map(c => c.body);
  assert.equal(bodies.length, 2);
  assert.deepEqual(bodies[0], bodies[1]);
});

test('network reconnection recovers registration even before a request ID was saved', async () => {
  const state = world('QUEUED');
  state.storage.delete('currentRequest');
  state.loseRegistration = true;
  const page = tab(state);
  await page.context.submitRegistration({ user_id: 'alice', section: 'A', party_size: 2 });
  page.events.get('online')();
  await settle();
  assert.equal(page.run('getCurrentRequest().request_id'), 'request-1');
  assert.equal(state.calls.filter(c => c.endpoint === 'waiting-room/submit').length, 2);
});

test('tabs share identity and clear stale user state after a storage event', async () => {
  const state = world();
  state.storage.delete('currentUser');
  state.storage.delete('currentRequest');
  const left = tab(state), right = tab(state);
  const users = await Promise.all([left.context.registerUser('Alice'), right.context.registerUser('Alice')]);
  assert.equal(users[0].user_id, users[1].user_id);
  state.storage.delete('currentUser');
  state.storage.delete('currentRequest');
  right.events.get('storage')({ key: 'currentUser' });
  assert.equal(right.run('getCurrentUser()'), null);
  assert.equal(right.element('checkout-step').hidden, true);
});

test('blocked storage retains this page state without claiming recovery after reload', async () => {
  const state = world('QUEUED');
  state.storage.clear();
  state.failWrites = true;
  const page = tab(state);
  const user = await page.context.registerUser('Alice');
  assert.equal(page.run('getCurrentUser().user_id'), user.user_id);
  const reloaded = tab(state);
  assert.equal(reloaded.run('getCurrentUser()'), null);
});

test('a stale response cannot populate another user checkout', async () => {
  const state = world();
  let release;
  const realFetch = state.fetch;
  state.fetch = async (...args) => {
    const response = await realFetch(...args);
    if (args[0].endsWith('/checkout')) await new Promise(resolve => { release = resolve; });
    return response;
  };
  const page = tab(state);
  const refresh = page.refresh();
  await settle();
  state.storage.set('currentUser', JSON.stringify({ name: 'Bob', user_id: 'bob' }));
  state.storage.delete('currentRequest');
  page.events.get('storage')({ key: 'currentUser' });
  release();
  await refresh;
  assert.equal(page.context.getCurrentCheckout(), null);
  assert.equal(page.element('checkout-step').hidden, true);
});
