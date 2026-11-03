// Queue state comes from waiting room; exact-hold outcomes come from checkout.
const STEPS = [
  ["REGISTERED", "Registered"], ["QUEUED", "Queued"],
  ["ADMITTED", "Admitted to a batch"], ["RESERVED", "Seats reserved"],
];
const BOOKING_TERMINAL = ["CONFIRMED", "CANCELLED", "EXPIRED", "UNAVAILABLE"];
let bookingTimer = null;
let trackedRequest = null;
let bookingGeneration = 0;
let bookingRefresh = null;
let checkoutState = null;
let checkoutVerified = false;

window.getCurrentCheckout = function () {
  const r = getCurrentRequest();
  return checkoutState?.request_id === r?.request_id && checkoutState?.hold_id === r?.allocation?.hold_id
    ? checkoutState : null;
};
window.isCheckoutVerified = () => checkoutVerified && Boolean(window.getCurrentCheckout());

function bookingStatus(r) {
  const state = window.getCurrentCheckout()?.booking_status;
  return state ? (state === "active" ? "RESERVED" : state.toUpperCase()) : r.status;
}

function stepsHtml(status) {
  const reached = BOOKING_TERMINAL.includes(status) ? STEPS.length
    : status === "ALLOCATION_DONE" ? 2 : STEPS.findIndex(([s]) => s === status);
  return `<ul class="steps">${STEPS.map(([, label], i) =>
    `<li class="${status === "UNAVAILABLE" && i === 3 ? "failed" : i < reached ? "done" : i === reached ? "current" : ""}">${esc(label)}</li>`
  ).join("")}</ul>`;
}

function renderBookingSummary(r, warning = "") {
  const box = document.getElementById("booking-result");
  if (!box || r.request_id !== getCurrentRequest()?.request_id) return;
  const status = bookingStatus(r);
  const checkout = window.getCurrentCheckout();
  const notes = {
    REGISTERED: "You are registered. Your queue number is drawn when the sale starts.",
    RESERVED: "Your seats are held. Complete payment before the original deadline.",
    CONFIRMED: "Your booking is confirmed. Your seats are secured.",
    CANCELLED: "Your reservation was cancelled. This request has ended.",
    EXPIRED: "Your hold expired. This request has ended and cannot be paid or rejoined.",
    UNAVAILABLE: "No adjacent seats were available. This request has ended.",
  };
  const allocation = r.allocation;
  const seatLabels = checkout?.seats?.map(s => typeof s === "string" ? s : s.seat_id)
    || allocation?.seats || [];
  box.innerHTML = stepsHtml(status) + (notes[status] ? message(notes[status]) : "")
    + (warning ? message(warning, true) : "") + `<dl>
      <dt>Status</dt><dd>${badge(status)}</dd>
      <dt>User</dt><dd>${esc(r.user_id)}</dd>
      <dt>Section</dt><dd>${esc(r.section)}</dd>
      <dt>Party size</dt><dd>${esc(r.party_size)}</dd>
      <dt>Queue number</dt><dd>${esc(r.queue_number ?? "Not drawn yet")}</dd>
      ${allocation ? `<dt>Seats</dt><dd>${esc(seatLabels.join(", "))}</dd>
        <dt>Hold ID</dt><dd>${esc(allocation.hold_id)}</dd>
        <dt>Hold status</dt><dd>${badge(status === "RESERVED" ? "ACTIVE" : status)}</dd>
        ${status === "RESERVED" ? `<dt>Pay before</dt><dd>${esc(new Date(checkout?.original_hold_expiry || allocation.hold_expiry).toLocaleTimeString())}</dd>` : ""}` : ""}
      <dt>Request ID</dt><dd>${esc(r.request_id)}</dd></dl>`;
}

async function loadBooking(requestId) {
  if (bookingRefresh) return bookingRefresh;
  const generation = bookingGeneration;
  const userId = getCurrentUser()?.user_id;
  const stillCurrent = () => generation === bookingGeneration
    && userId === getCurrentUser()?.user_id && requestId === getCurrentRequest()?.request_id;
  const work = (async () => {
    try {
      const r = await api("waiting-room/requests/" + encodeURIComponent(requestId));
      if (!stillCurrent() || r.user_id !== userId || r.request_id !== requestId) return null;
      setCurrentRequest(r);
      let warning = "";
      if (r.allocation?.hold_id) {
        try {
          const checkout = await api("waiting-room/requests/" + encodeURIComponent(requestId) + "/checkout");
          if (!stillCurrent()) return null;
          if (checkout.request_id !== requestId || checkout.hold_id !== r.allocation.hold_id
              || !["active", "confirmed", "cancelled", "expired"].includes(checkout.booking_status)
              || checkout.source !== "seat-store" || checkout.cached === true
              || (checkout.booking_status === "active" &&
                  Date.parse(checkout.hold_expiry) !== Date.parse(r.allocation.hold_expiry))) {
            throw new Error("Checkout identity or original deadline could not be verified");
          }
          const previous = window.getCurrentCheckout();
          if (previous && previous.booking_status !== "active" && checkout.booking_status !== previous.booking_status) {
            throw new Error("Conflicting booking outcome");
          }
          checkoutState = checkout;
          checkoutVerified = true;
        } catch (error) {
          if (!stillCurrent()) return null;
          checkoutVerified = false;
          warning = "Unable to verify checkout. Payment is paused; reconnecting automatically.";
        }
      } else {
        checkoutState = null;
        checkoutVerified = false;
      }
      renderBookingSummary(r, warning);
      window.renderCheckout?.();
      return bookingStatus(r);
    } catch (error) {
      if (!stillCurrent()) return null;
      checkoutVerified = false;
      renderBookingSummary(getCurrentRequest(), "Connection lost. Your request is saved; reconnecting automatically.");
      window.renderCheckout?.();
      return null;
    }
  })();
  bookingRefresh = work;
  try { return await work; }
  finally { if (bookingRefresh === work) bookingRefresh = null; }
}
window.refreshBooking = loadBooking;

function stopBooking() {
  clearInterval(bookingTimer);
  bookingTimer = null;
  trackedRequest = null;
  bookingGeneration++;
  bookingRefresh = null;
  checkoutState = null;
  checkoutVerified = false;
  document.getElementById("booking-result").innerHTML = "";
  window.stopCheckout?.();
}

function trackBooking(requestId) {
  if (trackedRequest === requestId && bookingTimer !== null) return;
  stopBooking();
  trackedRequest = requestId;
  const generation = bookingGeneration;
  const tick = async () => {
    if (!document.getElementById("join").classList.contains("active")) {
      if (generation === bookingGeneration) stopBooking();
      return;
    }
    const status = await loadBooking(requestId);
    if (generation !== bookingGeneration) return;
    if (BOOKING_TERMINAL.includes(status) && (status === "UNAVAILABLE" || checkoutVerified)) {
      clearInterval(bookingTimer);
      bookingTimer = null;
    }
  };
  // A temporary connection failure never ends polling or creates a new request.
  bookingTimer = setInterval(tick, 2000);
  tick();
}

window.addEventListener("online", () => {
  const r = getCurrentRequest();
  if (r && document.getElementById("join").classList.contains("active")) {
    trackBooking(r.request_id);
    loadBooking(r.request_id);
  }
});
