// Calls a backend service through server.py, e.g. api("waiting-room/submit", { ... }).
// A body makes it a POST; otherwise it is a GET. Throws with the service's error message.
async function api(path, body) {
  const options = body === undefined
    ? { method: "GET" }
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch("/api/" + path, options);
  let data;
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (!response.ok) {
    throw new Error(data.error || data.message || `Request failed (${response.status})`);
  }
  return data;
}

// Escapes text before it is placed into HTML.
function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function message(text, isError) {
  return `<div class="message${isError ? " error" : ""}">${esc(text)}</div>`;
}

const GOOD = ["RESERVED", "CONFIRMED", "ADMITTED", "ALLOCATION_DONE", "COMPLETED"];
const BAD = ["UNAVAILABLE", "EXPIRED", "CANCELLED"];

// Dispatcher batches in dispatch order (finished ones, then the active one).
// "Batch N" in the UI is the position in this list.
function dispatchedBatches(dispatcher) {
  if (!dispatcher) return [];
  return [...dispatcher.batch_history, ...(dispatcher.current ? [dispatcher.current] : [])];
}

function badge(status) {
  const kind = GOOD.includes(status) ? "ok" : BAD.includes(status) ? "bad" : "";
  return `<span class="badge ${kind}">${esc(status)}</span>`;
}
