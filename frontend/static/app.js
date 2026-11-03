// Tab switching, plus the registered user and their current request shared by every tab.

const tabHandlers = {};

// A tab file calls onTabOpen("seats", fn) to run fn each time that tab is shown.
function onTabOpen(tab, handler) {
  tabHandlers[tab] = handler;
}

function showTab(tab) {
  save("currentTab", tab);
  document.querySelectorAll("#tabs button").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll("main > section").forEach((s) =>
    s.classList.toggle("active", s.id === tab));
  if (tabHandlers[tab]) tabHandlers[tab]();
}

document.querySelectorAll("#tabs button").forEach((b) =>
  b.addEventListener("click", () => showTab(b.dataset.tab)));

// localStorage can be unavailable (e.g. private mode), so keep a fallback in memory.
const memory = {};
const volatileKeys = new Set();

function load(key) {
  if (volatileKeys.has(key)) return memory[key] ?? null;
  try {
    return JSON.parse(localStorage.getItem(key));
  } catch {
    return memory[key] ?? null;
  }
}

// Same-origin tabs serialize user actions where Web Locks is available. Server
// idempotency and deterministic checkout keys still protect concurrent requests.
function withBrowserLock(name, operation) {
  return navigator.locks ? navigator.locks.request("ticketing:" + name, operation) : operation();
}

function save(key, value) {
  memory[key] = value;
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
    volatileKeys.delete(key);
  } catch {
    // Memory copy is enough for this page.
    volatileKeys.add(key);
  }
}

// There is no account service, so the user (name + generated ID) only lives in this browser.
// "Register" in the UI means registering for the sale (waiting room /submit), as in the slides.
// user: { name, user_id }. Names may repeat; the generated UUID is the identity.
function getCurrentUser() {
  return load("currentUser");
}

async function registerUser(name) {
  return withBrowserLock("identity", () => {
    const existing = getCurrentUser();
    if (existing) return existing;
    const user = { name, user_id: crypto.randomUUID() };
    save("currentUser", user);
    save("currentRequest", null);
    renderHeader();
    return user;
  });
}

// request: the waiting-room record, at least { request_id, user_id, section, party_size }.
function getCurrentRequest() {
  return load("currentRequest");
}

function setCurrentRequest(request) {
  if (request && request.user_id !== getCurrentUser()?.user_id) return;
  save("currentRequest", request);
  renderHeader();
}

function renderHeader() {
  const user = getCurrentUser();
  const request = getCurrentRequest();
  let text = "No user yet";
  if (user) text = request
    ? `${user.name} · Section ${request.section} · ${request.party_size} pax`
    : user.name;
  document.getElementById("current-request").textContent = text;
  document.getElementById("switch-user").hidden = !user;
}

document.getElementById("switch-user").addEventListener("click", async () => {
  await withBrowserLock("identity", () => {
    save("currentUser", null);
    save("currentRequest", null);
  });
  renderHeader();
  showTab("join");
});

// localStorage changes reach other tabs, including identity switches. Never keep
// displaying the previous user's checkout after another tab switches users.
window.addEventListener("storage", (event) => {
  if (!["currentUser", "currentRequest", null].includes(event.key)) return;
  delete memory.currentUser;
  delete memory.currentRequest;
  volatileKeys.delete("currentUser");
  volatileKeys.delete("currentRequest");
  renderHeader();
  if (document.getElementById("join").classList.contains("active")) renderJoin();
});

renderHeader();

// Run the first tab's handler once every tab file has registered.
window.addEventListener("DOMContentLoaded", () => {
  const tab = load("currentTab");
  showTab(["admin", "batches", "seats", "join"].includes(tab)
    ? tab : document.querySelector("#tabs button.active").dataset.tab);
});
