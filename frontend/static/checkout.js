/* Ticket-style checkout using the existing mock-payment API.
 * No payment-card information is collected or stored.
 */
(() => {
  'use strict';
  const root = document.getElementById('checkout-step');
  if (!root) return;
  let timer = null;
  let busy = false;
  let activeRequest = null;
  let paymentId = null;
  let paymentStatus = null;
  let cancelActionId = null;
  let confirmed = false;
  let cancelled = false;
  let outcomeText = '';

  const keyFor = (kind, requestId) => `checkout:${kind}:${requestId}`;
  function stableKey(kind, requestId) {
    const key = keyFor(kind, requestId);
    let value = load(key);
    if (!value) {
      value = (globalThis.crypto && crypto.randomUUID) ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
      save(key, value);
    }
    return value;
  }
  function newKey(kind, requestId) { save(keyFor(kind, requestId), null); }
  function active() {
    const request = getCurrentRequest();
    return request?.status === 'RESERVED' && Boolean(request?.allocation?.hold_id);
  }
  function remaining(expiry) {
    const millis = new Date(expiry).getTime() - Date.now();
    if (!Number.isFinite(millis)) return null;
    return Math.max(0, Math.ceil(millis / 1000));
  }
  function formatClock(seconds) {
    if (seconds === null) return '--:--';
    return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
  }
  function hasEnded() {
    return confirmed || cancelled || Boolean(cancelActionId) || ['confirmed','succeeded','success','completed','paid'].includes(String(paymentStatus).toLowerCase());
  }
  function draw() {
    if (!active()) { root.hidden = true; clearInterval(timer); timer = null; return; }
    const r = getCurrentRequest();
    const a = r.allocation;
    if (activeRequest !== r.request_id) {
      activeRequest = r.request_id;
      paymentId = load(`checkout:payment:${activeRequest}`);
      cancelActionId = load(`checkout:cancel-id:${activeRequest}`);
      paymentStatus = null; confirmed = false; cancelled = false; outcomeText = '';
    }
    root.hidden = false;
    const secs = remaining(a.hold_expiry);
    const expired = secs === 0;
    const done = hasEnded();
    const blocked = busy || expired || done;
    const user = getCurrentUser();
    const seatLabels = Array.isArray(a.seats) ? a.seats.join(', ') : 'Assigned seats';

    // Cancellation is a separate terminal state: never display a countdown or
    // payment actions after cancellation has been requested or completed.
    if (cancelled || cancelActionId) {
      const isComplete = cancelled;
      root.innerHTML = `
        <div class="ticket-checkout ticket-confirmation" aria-label="Reservation cancellation">
          <div class="ticket-checkout-topline">
            <span class="ticket-eyebrow">RESERVATION STATUS</span>
            <span class="ticket-pill">${isComplete ? 'Cancelled' : 'Cancellation pending'}</span>
          </div>
          <section class="ticket-panel" role="status" aria-live="polite">
            <h2>${isComplete ? 'Reservation cancelled' : 'Cancelling your reservation…'}</h2>
            <p>${isComplete
              ? 'Your reservation has been cancelled.'
              : 'We have received your cancellation request and are waiting for confirmation. Payment is unavailable.'}</p>
            <div class="ticket-row"><span>Section</span><strong>${esc(r.section)}</strong></div>
            <div class="ticket-row"><span>Seats</span><strong>${esc(seatLabels)}</strong></div>
            <div class="ticket-row"><span>Request ID</span><span class="ticket-ref">${esc(r.request_id)}</span></div>
          </section>
        </div>`;
      return;
    }

    // A completed payment is a terminal booking, not an active checkout.
    // Show a ticket-style confirmation without a timer or further actions.
    if (confirmed || ['confirmed', 'succeeded', 'success', 'completed', 'paid'].includes(String(paymentStatus).toLowerCase())) {
      root.innerHTML = `
        <div class="ticket-checkout ticket-confirmation" aria-label="Booking confirmation">
          <div class="ticket-checkout-topline">
            <span class="ticket-eyebrow">BOOKING CONFIRMATION</span>
            <span class="ticket-pill">Confirmed</span>
          </div>
          <div class="ticket-confirmation-banner" role="status">
            <span class="ticket-confirmation-check" aria-hidden="true">✓</span>
            <div>
              <h2>Booking confirmed!</h2>
              <p>Your mock payment was successful. Your seats are confirmed.</p>
            </div>
          </div>
          <div class="ticket-confirmation-grid">
            <section class="ticket-panel">
              <h3>Your tickets</h3>
              <div class="ticket-event">
                <div class="ticket-event-icon" aria-hidden="true">T</div>
                <div><strong>Fair Seat Allocation</strong><span>Section ${esc(r.section)} · ${esc(r.party_size)} ${Number(r.party_size) === 1 ? 'ticket' : 'tickets'}</span></div>
              </div>
              <div class="ticket-row"><span>Seats</span><strong>${esc(seatLabels)}</strong></div>
              <div class="ticket-row"><span>Booking name</span><strong>${esc(user?.name || r.user_id)}</strong></div>
              <div class="ticket-row"><span>Booking reference</span><span class="ticket-ref">${esc(a.hold_id)}</span></div>
            </section>
            <aside class="ticket-panel ticket-confirmation-note">
              <h3>Payment completed</h3>
              <p>No further payment is required for this reservation.</p>
              <p>This was a simulated payment. No actual money was charged.</p>
            </aside>
          </div>
        </div>`;
      return;
    }

    root.innerHTML = `
      <div class="ticket-checkout" aria-label="Reservation checkout">
        <div class="ticket-checkout-topline"><span class="ticket-eyebrow">SECURE DEMO CHECKOUT</span><span class="ticket-pill">${done ? 'Completed' : expired ? 'Hold expired' : 'Seats held'}</span></div>
        <div class="ticket-checkout-heading"><div><h2>Complete your booking</h2><p>Review your reservation and finish before the hold expires.</p></div></div>
        <div class="ticket-countdown ${expired ? 'is-expired' : secs !== null && secs <= 60 ? 'is-urgent' : ''}" role="status" aria-live="off">
          <span class="ticket-timer-symbol" aria-hidden="true">◷</span>
          <div><span class="ticket-timer-label">${expired ? 'Your hold has expired' : 'Time remaining to complete checkout'}</span><strong id="ticket-clock">${formatClock(secs)}</strong></div>
          <small>Seats are only confirmed after successful payment.</small>
        </div>
        <div class="ticket-checkout-grid">
          <div class="ticket-checkout-main">
            <section class="ticket-panel"><div class="ticket-panel-head"><span class="ticket-step-number">1</span><h3>Ticket details</h3></div>
              <div class="ticket-event"><div class="ticket-event-icon" aria-hidden="true">T</div><div><strong>Fair Seat Allocation</strong><span>Section ${esc(r.section)} · ${esc(r.party_size)} ${Number(r.party_size) === 1 ? 'ticket' : 'tickets'}</span></div></div>
              <div class="ticket-row"><span>Reserved seats</span><strong>${esc(seatLabels)}</strong></div>
              <div class="ticket-row"><span>Reservation ID</span><span class="ticket-ref">${esc(r.request_id)}</span></div>
            </section>
            <section class="ticket-panel"><div class="ticket-panel-head"><span class="ticket-step-number">2</span><h3>Contact</h3></div>
              <div class="ticket-row"><span>Booking name</span><strong>${esc(user?.name || r.user_id)}</strong></div>
              <p class="ticket-helper">This is your demo booking identity. No email or real account is required.</p>
            </section>
            <section class="ticket-panel"><div class="ticket-panel-head"><span class="ticket-step-number">3</span><h3>Payment method</h3></div>
              <div class="ticket-payment-method"><span class="ticket-method-icon" aria-hidden="true">▣</span><div><strong>Simulated payment</strong><small>No real charges or card details</small></div><span class="ticket-selected">Selected</span></div>
              <p class="ticket-helper">Pay simulates a successful payment; Decline simulates a rejected attempt. You may retry after a declined attempt while the hold remains active.</p>
            </section>
          </div>
          <aside class="ticket-panel ticket-summary"><h3>Order summary</h3>
            <div class="ticket-summary-event">Fair Seat Allocation</div>
            <div class="ticket-row"><span>Section</span><strong>${esc(r.section)}</strong></div>
            <div class="ticket-row"><span>Quantity</span><strong>${esc(r.party_size)}</strong></div>
            <div class="ticket-row"><span>Seats</span><strong>${esc(seatLabels)}</strong></div>
            <div class="ticket-total"><span>Total</span><strong>Demo only</strong></div>
            <p class="ticket-helper">No ticket price or currency is provided by the current backend, so no amount is charged or displayed.</p>
            <button id="ticket-pay" class="ticket-primary" ${blocked ? 'disabled' : ''}>${busy ? 'Processing…' : confirmed ? 'Payment completed' : 'Complete mock payment'}</button>
            <button id="ticket-decline" class="ticket-outline" ${blocked ? 'disabled' : ''}>Simulate decline</button>
            <button id="ticket-cancel" class="ticket-text-btn" ${blocked ? 'disabled' : ''}>Cancel reservation</button>
            <div id="ticket-feedback" class="ticket-feedback" role="status" aria-live="polite">${esc(outcomeText || (expired ? 'Your hold is no longer valid. Please start a new request.' : 'Your seats are temporarily reserved.'))}</div>
          </aside>
        </div>
      </div>`;
    root.querySelector('#ticket-pay')?.addEventListener('click', () => sendPayment('success'));
    root.querySelector('#ticket-decline')?.addEventListener('click', () => sendPayment('decline'));
    root.querySelector('#ticket-cancel')?.addEventListener('click', cancelBooking);
  }
  async function queryPayment() {
    if (!paymentId) return;
    try {
      const p = await api(`payment/payments/${encodeURIComponent(paymentId)}`);
      paymentStatus = p.status;
      const s = String(p.status || '').toLowerCase();
      if (['confirmed', 'succeeded','success','completed','paid'].includes(s)) {
        confirmed = true;
        outcomeText = 'Payment completed. Your booking is confirmed.';
        // Payment GET is authoritative for the checkout outcome. Update the
        // booking summary only after confirming this exact payment/hold.
        window.updateBookingPaymentStatus?.(activeRequest, getCurrentRequest()?.allocation?.hold_id, 'confirmed');
      } else if (['declined', 'failed', 'rejected'].includes(s)) {
        outcomeText = 'Payment declined. You can retry before your hold expires.';
        newKey('pay', activeRequest);
        paymentId = null;
        save(`checkout:payment:${activeRequest}`, null);
      } else { outcomeText = `Payment status: ${p.status || 'pending'}`; }
    } catch { /* Temporary backend errors should not clear the attempt key. */ }
    draw();
  }
  async function sendPayment(outcome) {
    const r = getCurrentRequest();
    if (!r?.allocation?.hold_id || busy || hasEnded() || remaining(r.allocation.hold_expiry) === 0) return;
    busy = true; outcomeText = 'Submitting payment attempt…'; draw();
    try {
      // Each deliberate decline uses a separate simulated attempt. Pay retries reuse their key.
      const kind = outcome === 'success' ? 'pay' : 'decline';
      const key = stableKey(kind, r.request_id);
      const response = await api('payment/payments', {
        request_id: r.request_id, hold_id: r.allocation.hold_id,
        outcome, attempt_key: key,
      });
      paymentId = response.payment_id || null;
      paymentStatus = response.status || null;
      if (paymentId) save(`checkout:payment:${r.request_id}`, paymentId);
      outcomeText = `Payment submitted: ${paymentStatus || 'processing'}.`;
      if (outcome === 'decline') newKey('decline', r.request_id);
      if (paymentId) await queryPayment();
    } catch (e) { outcomeText = `Payment could not be confirmed: ${e.message}. Retry will reuse the same attempt key.`; }
    finally { busy = false; draw(); }
  }
  async function cancelBooking() {
    const r = getCurrentRequest();
    if (!r?.allocation?.hold_id || busy || hasEnded()) return;
    if (!window.confirm('Cancel this reservation and release the held seats?')) return;
    busy = true; outcomeText = 'Requesting cancellation…'; draw();
    try {
      const response = await api('payment/checkouts/cancel', {
        request_id: r.request_id, hold_id: r.allocation.hold_id,
        action_key: stableKey('cancel', r.request_id)
      });
      cancelActionId = response.action_id || null;
      if (cancelActionId) save(`checkout:cancel-id:${r.request_id}`, cancelActionId);
      outcomeText = `Cancellation requested: ${response.status || 'pending'}.`;
      if (['cancelled','completed'].includes(String(response.status).toLowerCase())) {
        cancelled = true;
        window.updateBookingCancellationStatus?.(r.request_id, r.allocation.hold_id, 'cancelled');
      }
    } catch (e) { outcomeText = `Cancellation could not be confirmed: ${e.message}. Retrying will use the same cancellation key.`; }
    finally { busy = false; draw(); }
  }
  async function poll() {
    if (!active()) { draw(); return; }
    if (!root.closest('#join')?.classList.contains('active')) return;
    const r = getCurrentRequest();
    if (paymentId && !confirmed) await queryPayment();
    if (cancelActionId && !cancelled) {
      try {
        const x = await api(`payment/cancellations/${encodeURIComponent(cancelActionId)}`);
        if (['cancelled','completed','succeeded'].includes(String(x.status).toLowerCase())) {
          cancelled = true; outcomeText = 'Reservation cancellation completed.';
          window.updateBookingCancellationStatus?.(r.request_id, r.allocation.hold_id, 'cancelled');
        }
      } catch { /* Keep polling while backend is temporarily unavailable. */ }
    }
    // Update the countdown even when payment services are unavailable.
    if (r?.request_id === getCurrentRequest()?.request_id) draw();
  }
  window.renderCheckout = function renderCheckout() {
    draw();
    if (timer !== null) clearInterval(timer);
    if (active()) timer = setInterval(poll, 1000);
  };
  window.stopCheckout = function stopCheckout() {
    clearInterval(timer); timer = null; root.hidden = true;
  };
})();
