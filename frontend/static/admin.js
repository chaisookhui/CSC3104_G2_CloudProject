// Admin > Overview: simulated users, sale controls and the live queue
// (waiting room /submit, /sale/start, /status, /queue; dispatcher /status).
// After Start sale, the dispatcher's own worker moves batches along every second.

let adminTimer = null;

// Shows the result of a click. Success notices clear after a few seconds because
// they describe that moment only; live progress is in the stats and table.
let notices = 0;

function notify(text, isError) {
  const box = document.getElementById("admin-message");
  const id = ++notices;
  box.innerHTML = message(text, isError);
  // Clear only if no newer notice has replaced this one.
  if (!isError) setTimeout(() => { if (notices === id) box.innerHTML = ""; }, 6000);
}

function pick(value, options) {
  return value === "Random" ? options[Math.floor(Math.random() * options.length)] : value;
}

async function loadAdmin() {
  try {
    const [status, queue, dispatcher] = await Promise.all([
      api("waiting-room/status"),
      api("waiting-room/queue"),
      api("dispatcher/status").catch(() => null),
    ]);
    const batches = dispatchedBatches(dispatcher);
    const batchNumber = new Map(batches.map((b, i) => [b.batch_id, i + 1]));
    let batch = "not reachable";
    if (dispatcher) batch = dispatcher.current
      ? `Batch ${batches.length} · ${dispatcher.current.state}`
      : `${dispatcher.batch_state} · ${dispatcher.batch_history.length} done`;
    document.getElementById("sale-status").innerHTML = `
      <div class="stats">
        <div class="stat"><b>${esc(status.sale_state)}</b>Sale state</div>
        <div class="stat"><b>${esc(status.waiting_count)}</b>Registered before sale</div>
        <div class="stat"><b>${esc(status.latecomer_count)}</b>Latecomers</div>
        <div class="stat"><b>${esc(status.queued_count)}</b>Still queued</div>
        <div class="stat"><b>${esc(batch)}</b>Dispatcher${dispatcher ? ` (batch size ${esc(dispatcher.batch_size)})` : ""}</div>
      </div>`;
    const me = getCurrentUser()?.user_id;
    const rows = queue.requests.map((r) => {
      // The waiting room keeps batch_id while admitted and last_batch_id after the outcome.
      const number = batchNumber.get(r.batch_id || r.last_batch_id);
      return `
      <tr${r.user_id === me ? ' class="me"' : ""}>
        <td>${esc(r.queue_number ?? "-")}${r.entry_type === "latecomer" ? ' <span class="badge">latecomer</span>' : ""}</td>
        <td>${esc(r.user_id)}</td>
        <td>${esc(r.section)}</td>
        <td>${esc(r.party_size)}</td>
        <td>${number ? `Batch ${number}` : "-"}</td>
        <td>${badge(r.status)}</td>
      </tr>`;
    }).join("");
    document.getElementById("queue-table").innerHTML = queue.count
      ? `<div class="table-wrap"><table>
           <tr><th>Queue #</th><th>User</th><th>Section</th><th>Party</th><th>Batch</th><th>Status</th></tr>
           ${rows}
         </table></div>`
      : `<p class="muted">Nobody has registered yet.</p>`;
  } catch (error) {
    document.getElementById("sale-status").innerHTML = message(error.message, true);
  }
}

// Registers fake users through the same endpoint real users use, 10 at a time.
document.getElementById("simulate-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const count = Math.min(500, Math.max(1, Number(form.get("count")) || 0));
  const run = Math.random().toString(36).slice(2, 6);
  let added = 0;
  let failed = 0;
  for (let start = 0; start < count; start += 10) {
    const chunk = [];
    for (let i = start; i < Math.min(count, start + 10); i++) {
      chunk.push(api("waiting-room/submit", {
        user_id: `sim-${run}-${i + 1}`,
        section: pick(form.get("section"), ["A", "B", "C", "D"]),
        party_size: Number(pick(form.get("party_size"), ["1", "2", "3", "4"])),
      }));
    }
    const results = await Promise.allSettled(chunk);
    added += results.filter((r) => r.status === "fulfilled").length;
    failed += results.filter((r) => r.status === "rejected").length;
    notices++;  // Progress replaces any earlier notice.
    document.getElementById("admin-message").innerHTML = message(`Adding users... ${added}/${count}`);
  }
  notify(`Added ${added} simulated users.` + (failed ? ` ${failed} failed.` : ""), failed > 0);
  loadAdmin();
});

document.getElementById("start-sale").addEventListener("click", async () => {
  try {
    const result = await api("waiting-room/sale/start", {});
    if (result.already_started) notify("Sale was already started.");
    else notify(`Sale started. ${result.initial_count} parties were given random queue numbers.` +
      (result.dispatcher_triggered ? " Batches now run automatically." : " Dispatcher was not reached."),
      !result.dispatcher_triggered);
  } catch (error) {
    notify(error.message, true);
  }
  loadAdmin();
});

document.getElementById("refresh-queue").addEventListener("click", loadAdmin);

// Refresh every 3 seconds while the tab is open.
onTabOpen("admin", () => {
  loadAdmin();
  clearInterval(adminTimer);
  adminTimer = setInterval(() => {
    if (document.getElementById("admin").classList.contains("active")) loadAdmin();
    else clearInterval(adminTimer);
  }, 3000);
});
