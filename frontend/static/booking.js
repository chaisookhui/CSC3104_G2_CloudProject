// User > My booking (below the register form): follow the user's request through the flow
// (waiting room GET /requests/<id>).

const STEPS = [
  ["REGISTERED", "Registered"],
  ["QUEUED", "Queued"],
  ["ADMITTED", "Admitted to a batch"],
  ["RESERVED", "Seats reserved"],
];

let bookingTimer = null;

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

function allocationHtml(allocation) {
  if (!allocation) return "";
  const expiry = allocation.hold_expiry
    ? new Date(allocation.hold_expiry).toLocaleTimeString()
    : "-";
  return `
    <dt>Seats</dt><dd>${esc(allocation.seats.join(", "))}</dd>
    <dt>Hold ID</dt><dd>${esc(allocation.hold_id)}</dd>
    <dt>Hold status</dt><dd>${badge(allocation.hold_status)}</dd>
    <dt>Pay before</dt><dd>${esc(expiry)}</dd>`;
}

async function loadBooking(requestId) {
  const box = document.getElementById("booking-result");
  try {
    const r = await api("waiting-room/requests/" + encodeURIComponent(requestId));
    // Ignore a reply that arrives after "Switch user".
    if (r.user_id !== getCurrentUser()?.user_id) return null;
    setCurrentRequest(r);
    let note = "";
    if (r.status === "REGISTERED") note = message("You are registered for the sale. Your queue number is drawn at random when the sale starts.");
    if (r.status === "RESERVED") note = message("Your seats are held. Pay before the hold expires.");
    if (r.status === "UNAVAILABLE") note = message("No adjacent seats were left for your party. This request has ended.", true);
    box.innerHTML = stepsHtml(r.status) + note + `
      <dl>
        <dt>Status</dt><dd>${badge(r.status)}</dd>
        <dt>User</dt><dd>${esc(r.user_id)}</dd>
        <dt>Section</dt><dd>${esc(r.section)}</dd>
        <dt>Party size</dt><dd>${esc(r.party_size)}</dd>
        <dt>Queue number</dt><dd>${esc(r.queue_number ?? "Not drawn yet")}</dd>
        ${allocationHtml(r.allocation)}
        <dt>Request ID</dt><dd>${esc(r.request_id)}</dd>
      </dl>`;
    return r.status;
  } catch (error) {
    box.innerHTML = message(error.message, true);
    return null;
  }
}

function stopBooking() {
  clearInterval(bookingTimer);
  document.getElementById("booking-result").innerHTML = "";
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
