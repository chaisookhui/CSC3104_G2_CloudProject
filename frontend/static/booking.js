// User > My booking (below the register form): follow the user's request through the flow
// (waiting room GET /requests/<id>).

const STEPS = [
  ["REGISTERED", "Registered"],
  ["QUEUED", "Queued"],
  ["ADMITTED", "Admitted to a batch"],
  ["RESERVED", "Seats reserved"],
];

let bookingTimer = null;
// This is a UI projection of an outcome verified by the Payment API.
// It does not change the original waiting-room request or the database.
let confirmedBooking = null;
let cancelledBooking = null;

window.updateBookingPaymentStatus = function updateBookingPaymentStatus(requestId, holdId, status) {
  const r = getCurrentRequest();
  if (!r || r.request_id !== requestId || r.allocation?.hold_id !== holdId) return;
  if (String(status).toLowerCase() !== "confirmed") return;
  confirmedBooking = { requestId, holdId };
  renderBookingSummary(r);
};

window.updateBookingCancellationStatus = function updateBookingCancellationStatus(requestId, holdId, status) {
  const r = getCurrentRequest();
  if (!r || r.request_id !== requestId || r.allocation?.hold_id !== holdId) return;
  if (String(status).toLowerCase() !== 'cancelled') return;
  cancelledBooking = { requestId, holdId };
  renderBookingSummary(r);
};

function isBookingCancelled(r) {
  return !!(cancelledBooking &&
    cancelledBooking.requestId === r.request_id &&
    cancelledBooking.holdId === r.allocation?.hold_id);
}

function isBookingConfirmed(r) {
  return !!(confirmedBooking &&
    confirmedBooking.requestId === r.request_id &&
    confirmedBooking.holdId === r.allocation?.hold_id);
}


function stepsHtml(status) {
  // ALLOCATION_DONE is reached between ADMITTED and the final outcome.
  const reached = status === "ALLOCATION_DONE" ? 2 : STEPS.findIndex(([s]) => s === status);
  const failed = status === "UNAVAILABLE";
  return `<ul class="steps">${STEPS.map(([, label], i) => {
    let cls = "";
    if (failed && i === STEPS.length - 1) return `<li class="failed">No seats available</li>`;
    if (failed || i < reached) cls = "done";
    else if (i === reached) cls = status === "RESERVED" ? "done" : "current";
    return `<li class="${cls}">${label}</li>`;
  }).join("")}</ul>`;
}

function allocationHtml(allocation, isConfirmed = false, isCancelled = false) {
  if (!allocation) return "";
  const expiry = allocation.hold_expiry
    ? new Date(allocation.hold_expiry).toLocaleTimeString()
    : "-";
  return `
    <dt>Seats</dt><dd>${esc(allocation.seats.join(", "))}</dd>
    <dt>Hold ID</dt><dd>${esc(allocation.hold_id)}</dd>
    <dt>Hold status</dt><dd>${badge(isConfirmed ? "CONFIRMED" : isCancelled ? "CANCELLED" : allocation.hold_status)}</dd>
    ${isConfirmed ? '<dt>Payment</dt><dd>Completed</dd>' : isCancelled ? '<dt>Reservation</dt><dd>Cancelled</dd>' : `<dt>Pay before</dt><dd>${esc(expiry)}</dd>`}`;
}

function renderBookingSummary(r) {
  const box = document.getElementById("booking-result");
  if (!box || r.request_id !== getCurrentRequest()?.request_id) return;
  const isConfirmed = isBookingConfirmed(r);
  const isCancelled = !isConfirmed && isBookingCancelled(r);
  const status = isConfirmed ? "CONFIRMED" : isCancelled ? "CANCELLED" : r.status;
  let note = "";
  if (r.status === "REGISTERED") note = message("You are registered for the sale. Your queue number is drawn at random when the sale starts.");
  if (isConfirmed) note = message("Your booking is confirmed. Your seats are secured.");
  else if (isCancelled) note = message("Your reservation has been cancelled.");
  else if (r.status === "RESERVED") note = message("Your seats are held. Pay before the hold expires.");
  if (r.status === "UNAVAILABLE") note = message("No adjacent seats were left for your party. This request has ended.", true);
  box.innerHTML = stepsHtml(r.status) + note + `
    <dl>
      <dt>Status</dt><dd>${badge(status)}</dd>
      <dt>User</dt><dd>${esc(r.user_id)}</dd>
      <dt>Section</dt><dd>${esc(r.section)}</dd>
      <dt>Party size</dt><dd>${esc(r.party_size)}</dd>
      <dt>Queue number</dt><dd>${esc(r.queue_number ?? "Not drawn yet")}</dd>
      ${allocationHtml(r.allocation, isConfirmed, isCancelled)}
      <dt>Request ID</dt><dd>${esc(r.request_id)}</dd>
    </dl>`;
}

async function loadBooking(requestId) {
  const box = document.getElementById("booking-result");
  try {
    const r = await api("waiting-room/requests/" + encodeURIComponent(requestId));
    // Ignore replies for an earlier user or request after switching accounts.
    if (r.user_id !== getCurrentUser()?.user_id ||
        r.request_id !== getCurrentRequest()?.request_id) return null;
    setCurrentRequest(r);
    renderBookingSummary(r);
    if (window.renderCheckout) window.renderCheckout();
    return r.status;
  } catch (error) {
    box.innerHTML = message(error.message, true);
    return null;
  }
}

function stopBooking() {
  clearInterval(bookingTimer);
  confirmedBooking = null;
  cancelledBooking = null;
  document.getElementById("booking-result").innerHTML = "";
  if (window.stopCheckout) window.stopCheckout();
}

// Poll every 2 seconds until the request reaches a final outcome or the tab is closed.
function trackBooking(requestId) {
  clearInterval(bookingTimer);
  const tick = async () => {
    const status = await loadBooking(requestId);
    const open = document.getElementById("join").classList.contains("active");
    if (!open || status === null || status === "RESERVED" || status === "UNAVAILABLE") {
      clearInterval(bookingTimer);
    }
  };
  tick();
  bookingTimer = setInterval(tick, 2000);
}
