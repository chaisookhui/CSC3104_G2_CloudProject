// User > My booking: enter a name, then register for the sale (waiting room POST /submit).
// Once registered, the booking status from booking.js appears below in the same tab.

const demoRequests = new Map();
let userSelection = 0;

function renderDemoUserOptions() {
  const select = document.getElementById("demo-user-select");
  const selected = select.value || getCurrentUser()?.user_id;
  const users = new Map([...demoRequests.keys()].map(user_id => [user_id, { user_id, name: user_id }]));
  for (const user of savedDemoUsers()) users.set(user.user_id, user);
  select.innerHTML = '<option value="">Choose a user</option>' + [...users.values()]
    .sort((left, right) => (left.name || left.user_id).localeCompare(right.name || right.user_id))
    .map(user => {
      const request = demoRequests.get(user.user_id);
      const label = `${user.name || user.user_id}${user.name && user.name !== user.user_id ? ' · ' + user.user_id : ''}`
        + (request ? ` · ${request.section} · ${request.party_size} pax` : '');
      return `<option value="${esc(user.user_id)}">${esc(label)}</option>`;
    }).join('');
  select.value = users.has(selected) ? selected : "";
  document.getElementById("view-demo-user").disabled = !select.value;
}

async function loadDemoUsers() {
  renderDemoUserOptions();
  try {
    const queue = await api("waiting-room/queue");
    demoRequests.clear();
    for (const request of queue.requests) demoRequests.set(request.user_id, request);
    renderDemoUserOptions();
    document.getElementById("demo-user-message").innerHTML = "";
  } catch (error) {
    document.getElementById("demo-user-message").innerHTML = message(
      'Could not refresh users. Saved users are still available. ' + error.message, true);
  }
}

async function viewDemoUser(userId) {
  if (!userId) return;
  const selection = ++userSelection;
  const saved = savedDemoUsers().find(user => user.user_id === userId);
  const previous = load("demoRequest:" + userId);
  const requestId = demoRequests.get(userId)?.request_id || previous?.request_id;
  try {
    // Retrieve existing state; never submit a new registration when switching.
    const request = requestId ? await api("waiting-room/requests/" + encodeURIComponent(requestId)) : null;
    if (selection !== userSelection) return;
    if (request && request.user_id !== userId) throw new Error('The request belongs to a different user.');
    await withBrowserLock("identity", () => {
      if (selection !== userSelection) return;
      selectDemoIdentity(saved || { name: userId, user_id: userId }, request);
    });
    if (selection !== userSelection) return;
    document.getElementById("demo-user-message").innerHTML = "";
    renderJoin();
  } catch (error) {
    if (selection === userSelection) document.getElementById("demo-user-message").innerHTML = message(
      'Could not open this user. If demo data was reset, create a new user. ' + error.message, true);
  }
}

document.getElementById("demo-user-select").addEventListener("change", event => {
  document.getElementById("view-demo-user").disabled = !event.target.value;
});
document.getElementById("view-demo-user").addEventListener("click", () =>
  viewDemoUser(document.getElementById("demo-user-select").value));
document.getElementById("refresh-demo-users").addEventListener("click", loadDemoUsers);
document.getElementById("new-demo-user").addEventListener("click", () => {
  userSelection++;
  selectDemoIdentity(null);
  document.getElementById("demo-user-select").value = "";
  document.getElementById("demo-user-message").innerHTML = "";
  renderJoin();
  document.querySelector('#register-form input[name="name"]').focus();
});

function renderJoin() {
  renderDemoUserOptions();
  const user = getCurrentUser();
  const savedRequest = getCurrentRequest();
  const request = savedRequest?.user_id === user?.user_id ? savedRequest : null;
  document.getElementById("register-step").hidden = Boolean(user);
  // One active request per user: once joined, show the booking instead of the form.
  document.getElementById("join-step").hidden = !user || Boolean(request);
  document.getElementById("booking-step").hidden = !request;
  document.getElementById("join-result").innerHTML = "";
  if (user) {
    document.getElementById("join-greeting").textContent = `Hi ${user.name}, choose your section and party size.`;
  }
  if (request) trackBooking(request.request_id);
  else {
    stopBooking();
    const pending = user && load("registration:" + user.user_id);
    if (pending) submitRegistration(pending);
  }
}

document.getElementById("register-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = new FormData(event.target).get("name").trim();
  if (!name) return;
  try {
    await registerUser(name);
    event.target.reset();
    renderJoin();
  } catch(error) {
    document.getElementById('demo-user-message').innerHTML=message(error.message,true);
  }
});

const joiningUsers = new Set();
async function submitRegistration(payload) {
  if (joiningUsers.has(payload.user_id)) return;
  joiningUsers.add(payload.user_id);
  try {
    await withBrowserLock("registration:" + payload.user_id, async () => {
      if (getCurrentUser()?.user_id !== payload.user_id) return;
      // Persist BEFORE sending: reload after a lost response replays the same
      // user registration, which the queue atomically deduplicates.
      save("registration:" + payload.user_id, payload);
      const request = await api("waiting-room/submit", payload);
      if (getCurrentUser()?.user_id !== payload.user_id) return;
      setCurrentRequest(request);
      save("registration:" + payload.user_id, null);
      renderJoin();
    });
  } catch (error) {
    if (getCurrentUser()?.user_id === payload.user_id) document.getElementById("join-result").innerHTML = message(
      "Registration could not be verified. Retry or reload to recover the same request. " + error.message, true);
  } finally {
    joiningUsers.delete(payload.user_id);
  }
}

document.getElementById("join-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  const user = getCurrentUser();
  if (!user) return;
  await submitRegistration(load("registration:" + user.user_id) || {
      user_id: user.user_id,
      section: form.get("section"),
      party_size: Number(form.get("party_size")),
    });
});

onTabOpen("join", () => { renderJoin(); loadDemoUsers(); });

window.addEventListener("online", () => {
  const user = getCurrentUser();
  if (user && !getCurrentRequest() && document.getElementById("join").classList.contains("active")) {
    const pending = load("registration:" + user.user_id);
    if (pending) submitRegistration(pending);
  }
});
