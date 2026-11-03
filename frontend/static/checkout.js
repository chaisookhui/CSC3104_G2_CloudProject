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
  let cancelActionId = null;
  let confirmed = false;
  let cancelled = false;
  let outcomeText = '';

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
    return confirmed || cancelled || Boolean(cancelActionId)
      || window.getCurrentCheckout()?.booking_status === 'expired';
  }
  function draw() {
    if (!active()) { root.hidden = true; clearInterval(timer); timer = null; return; }
    const r = getCurrentRequest();
    const a = r.allocation;
    if (activeRequest !== r.request_id) {
      activeRequest = r.request_id;
      busy = false; outcomeText = '';
    }
    const checkout = window.getCurrentCheckout();
    confirmed = checkout?.booking_status === 'confirmed';
    cancelled = checkout?.booking_status === 'cancelled';
    cancelActionId = checkout?.cancellation?.status === 'pending' ? checkout.cancellation.action_id : null;
    root.hidden = false;
    const secs = remaining(checkout?.original_hold_expiry || a.hold_expiry);
    const expired = checkout?.booking_status === 'expired';
    const done = hasEnded();
    const verified = window.isCheckoutVerified();
    const blocked = busy || !verified || !checkout?.can_pay || secs === 0 || done;
    const cancelBlocked = busy || !verified || !checkout?.can_cancel || done;
    const user = getCurrentUser();
    const seats = checkout?.seats?.map(s => typeof s === 'string' ? s : s.seat_id) || a.seats;
    const seatLabels = Array.isArray(seats) ? seats.join(', ') : 'Assigned seats';

    // Cancellation is a separate terminal state: never display a countdown or
    // payment actions after cancellation has been requested or completed.
    if (!confirmed && (cancelled || cancelActionId)) {
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
    if (confirmed) {
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

    if (expired) {
      root.innerHTML = `<div class="ticket-checkout ticket-confirmation">
        <h2>Reservation expired</h2>
        <p>Your original hold has ended. These seats are no longer reserved for you.</p>
        <div class="ticket-row"><span>Previous seats</span><strong>${esc(seatLabels)}</strong></div>
        <div class="ticket-row"><span>Request ID</span><span class="ticket-ref">${esc(r.request_id)}</span></div>
        <p>This request cannot be paid or rejoined.</p></div>`;
      return;
    }

    const latest = checkout?.payment_attempts?.at(-1);
    const feedback = !verified ? 'Checking your saved reservation. Actions are paused until the server responds.'
      : latest?.attempt_status === 'pending' ? 'Payment is processing. Reconnecting will recover this same attempt.'
      : outcomeText || (latest?.attempt_status === 'declined'
        ? 'Payment declined. Retry before the original hold deadline.'
        : secs === 0 ? 'The hold deadline has elapsed. Checking the final booking outcome.'
        : 'Your seats are temporarily reserved.');

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
            <button id="ticket-cancel" class="ticket-text-btn" ${cancelBlocked ? 'disabled' : ''}>Cancel reservation</button>
            <div id="ticket-feedback" class="ticket-feedback" role="status" aria-live="polite">${esc(feedback)}</div>
          </aside>
        </div>
      </div>`;
    root.querySelector('#ticket-pay')?.addEventListener('click', () => sendPayment('success'));
    root.querySelector('#ticket-decline')?.addEventListener('click', () => sendPayment('decline'));
    root.querySelector('#ticket-cancel')?.addEventListener('click', cancelBooking);
  }
  async function sendPayment(outcome) {
    const r = getCurrentRequest();
    const original = window.getCurrentCheckout();
    if (!r?.allocation?.hold_id || busy || !window.isCheckoutVerified() || !original?.can_pay || hasEnded()) return;
    const holdId = r.allocation.hold_id;
    const expectedAttempts = original.payment_attempts.length;
    const current = () => getCurrentRequest()?.request_id === r.request_id
      && getCurrentUser()?.user_id === r.user_id;
    busy = true; outcomeText = 'Submitting payment attempt...'; draw();
    try {
      await withBrowserLock('checkout:' + holdId, async () => {
        await window.refreshBooking(r.request_id);
        const checkout = window.getCurrentCheckout();
        if (!current() || !window.isCheckoutVerified() || !checkout?.can_pay
            || checkout.payment_attempts.length !== expectedAttempts) return;
        // The server-observed attempt number gives every tab the same identity.
        // A conflicting simultaneous Pay/Decline cannot create a second attempt.
        await api('payment/payments', {
          request_id: r.request_id, hold_id: holdId, outcome,
          attempt_key: `browser:${holdId}:${expectedAttempts}`,
        });
        if (current()) {
          outcomeText = 'Payment submitted. Waiting for the verified booking outcome.';
          await window.refreshBooking(r.request_id);
        }
      });
    } catch (e) {
      if (current()) {
        outcomeText = 'Payment response unavailable. Checking the saved attempt before any retry.';
        await window.refreshBooking(r.request_id);
      }
    } finally {
      if (current()) { busy = false; draw(); }
    }
  }
  async function cancelBooking() {
    const r = getCurrentRequest();
    if (!r?.allocation?.hold_id || busy || !window.isCheckoutVerified()
        || !window.getCurrentCheckout()?.can_cancel || hasEnded()) return;
    if (!window.confirm('Cancel this reservation and release the held seats?')) return;
    const holdId = r.allocation.hold_id;
    const current = () => getCurrentRequest()?.request_id === r.request_id
      && getCurrentUser()?.user_id === r.user_id;
    busy = true; outcomeText = 'Requesting cancellation...'; draw();
    try {
      await withBrowserLock('checkout:' + holdId, async () => {
        await window.refreshBooking(r.request_id);
        if (!current() || !window.isCheckoutVerified() || !window.getCurrentCheckout()?.can_cancel) return;
        await api('payment/checkouts/cancel', {
          request_id: r.request_id, hold_id: holdId, action_key: 'browser-cancel:' + holdId,
        });
        if (current()) await window.refreshBooking(r.request_id);
      });
    } catch (e) {
      if (current()) {
        outcomeText = 'Cancellation response unavailable. Checking the saved action before retrying.';
        await window.refreshBooking(r.request_id);
      }
    } finally {
      if (current()) { busy = false; draw(); }
    }
  }
  window.renderCheckout = function renderCheckout() {
    draw();
    if (timer !== null) clearInterval(timer);
    timer = active() && !hasEnded() ? setInterval(draw, 1000) : null;
  };
  window.stopCheckout = function stopCheckout() {
    clearInterval(timer); timer = null; root.hidden = true;
  };
})();