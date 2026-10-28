// Admin > Batches: how the allocator ordered each batch, per section (demand cycle).
// Batches come from dispatcher /status; jobs, rank and turn order from allocation /batches/<id>.

const SIZES = [1, 2, 3, 4];

let batchesTimer = null;
let chosenBatch = null; // batch_id, or null to follow the latest batch

// Demand counts the dispatcher sent; falls back to counting the batch's jobs.
function demandFor(record, jobs, section) {
  const sent = record.allocator_input?.section_demand?.[section];
  return Object.fromEntries(SIZES.map((size) => [size,
    sent ? Number(sent[size] ?? 0) : jobs.filter((j) => j.party_size === size).length]));
}

// Jobs are in turn order; a new round starts when a party size comes up again.
function rounds(jobs) {
  const result = [];
  let round = [];
  for (const job of jobs) {
    if (round.some((j) => j.party_size === job.party_size)) {
      result.push(round);
      round = [];
    }
    round.push(job);
  }
  if (round.length) result.push(round);
  return result;
}

function partyChip(job) {
  const kind = { RESERVED: "ok", UNAVAILABLE: "bad", IN_PROGRESS: "active" }[job.state] || "";
  const mine = job.request_id === getCurrentRequest()?.request_id ? " me" : "";
  const seats = job.result?.seats?.join(", ");
  const title = `Queue #${job.global_position} · party of ${job.party_size} · ${job.state}` +
    (seats ? ` · ${seats}` : "");
  return `<span class="chip ${kind}${mine}" title="${esc(title)}"><b>${esc(job.party_size)}</b>#${esc(job.global_position)}</span>`;
}

function sectionHtml(section, record, allocation) {
  const jobs = allocation.jobs
    .filter((j) => j.section === section)
    .sort((a, b) => a.priority - b.priority);
  if (!jobs.length) {
    return `<div class="section-card"><h3>Section ${section}</h3><p class="muted">No parties in this batch.</p></div>`;
  }
  const demand = demandFor(record, jobs, section);
  const reserved = jobs.filter((j) => j.state === "RESERVED").length;
  const rank = (allocation.size_order?.[section] || [])
    .map((size) => `<span class="chip"><b>${esc(size)}</b>×${esc(demand[size])}</span>`)
    .join('<span class="muted">→</span>');
  const turns = rounds(jobs).map((round, i) =>
    `<div class="round"><span class="round-label">Round ${i + 1}</span>${round.map(partyChip).join("")}</div>`).join("");
  return `
    <div class="section-card">
      <h3>Section ${section} <span class="muted">${reserved}/${jobs.length} reserved</span></h3>
      <div class="label">Rank by demand (size × parties)</div>
      <div class="round">${rank}</div>
      <div class="label">Seating order</div>
      ${turns}
    </div>`;
}

async function loadBatches() {
  const picker = document.getElementById("batch-picker");
  const detail = document.getElementById("batch-detail");
  try {
    const records = dispatchedBatches(await api("dispatcher/status"));
    if (!records.length) {
      picker.innerHTML = "";
      detail.innerHTML = `<p class="muted">No batches yet. Start the sale in Admin.</p>`;
      return;
    }
    const shown = records.find((r) => r.batch_id === chosenBatch) || records[records.length - 1];
    picker.innerHTML = records.map((r, i) =>
      `<button data-index="${i}" class="${r === shown ? "" : "secondary"}">Batch ${i + 1}</button>`).join("");
    picker.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      const i = Number(b.dataset.index);
      // Choosing the newest batch keeps following new batches as they start.
      chosenBatch = i === records.length - 1 ? null : records[i].batch_id;
      loadBatches();
    }));

    const header = `<p><b>Batch ${records.indexOf(shown) + 1}</b> · ${esc(shown.batch_size)} parties ·
      dispatcher ${badge(shown.state)}</p>`;
    let allocation;
    try {
      allocation = await api("allocation/batches/" + encodeURIComponent(shown.batch_id));
    } catch {
      detail.innerHTML = header + `<p class="muted">The allocator has not received this batch yet.</p>`;
      return;
    }
    const legend = `<p class="muted legend">
      <span class="chip"><b>2</b>#7</span> party of 2, queue #7 ·
      <span class="chip ok">reserved</span> <span class="chip bad">unavailable</span>
      <span class="chip active">being seated</span> <span class="chip">waiting</span>
      <span class="chip me">you</span> · hover a party for its seats</p>`;
    detail.innerHTML = header + legend +
      `<div class="sections">${["A", "B", "C", "D"].map((s) => sectionHtml(s, shown, allocation)).join("")}</div>`;
  } catch (error) {
    detail.innerHTML = message(error.message, true);
  }
}

// Refresh every 3 seconds while the tab is open, so a running batch fills in live.
onTabOpen("batches", () => {
  loadBatches();
  clearInterval(batchesTimer);
  batchesTimer = setInterval(() => {
    if (document.getElementById("batches").classList.contains("active")) loadBatches();
    else clearInterval(batchesTimer);
  }, 3000);
});
