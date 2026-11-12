// Each browser tab chooses its own view/user; booking records stay shared by user ID.

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

// Selection belongs to this tab. Durable records belong to a user, so another
// tab can view that same booking without changing anyone else's selected user.
const memory = {};
const volatileKeys = new Set();
const sessionKeys = new Set(["currentUser", "currentTab"]);

function storageKey(key) {
  return key === "currentRequest" ? "demoRequest:" + getCurrentUser()?.user_id : key;
}

function load(key) {
  if (key === "currentRequest" && !getCurrentUser()) return null;
  const storedKey = storageKey(key);
  if (volatileKeys.has(storedKey)) return memory[storedKey] ?? null;
  try {
    return JSON.parse((sessionKeys.has(key) ? sessionStorage : localStorage).getItem(storedKey));
  } catch {
    return memory[storedKey] ?? null;
  }
}

// Same-origin tabs serialize user actions where Web Locks is available. Server
// idempotency and deterministic checkout keys still protect concurrent requests.
function withBrowserLock(name, operation) {
  return navigator.locks ? navigator.locks.request("ticketing:" + name, operation) : operation();
}

function save(key, value) {
  if (key === "currentRequest" && !getCurrentUser()) return;
  const storedKey = storageKey(key);
  memory[storedKey] = value;
  try {
    const storage = sessionKeys.has(key) ? sessionStorage : localStorage;
    if (value === null) storage.removeItem(storedKey);
    else storage.setItem(storedKey, JSON.stringify(value));
    volatileKeys.delete(storedKey);
  } catch {
    // Memory copy is enough for this page.
    volatileKeys.add(storedKey);
  }
}

function savedDemoUsers() {
  const users = load("demoUsers");
  return Array.isArray(users) ? users.filter(user => typeof user?.user_id === "string" &&
    (!window.allowedBrowserUsers || window.allowedBrowserUsers.has(user.user_id))) : [];
}

function rememberDemoUser(user) {
  const cached=load('demoUsers');
  save("demoUsers", [...(Array.isArray(cached)?cached:[]).filter(saved => saved?.user_id !== user.user_id), user]);
}

// Preserve the previous frontend's saved booking once when upgrading. Subsequent
// new tabs start independently; reloads restore their own session selection.
try {
  const legacyUser = JSON.parse(localStorage.getItem("currentUser"));
  if (!load("demoUsers") && legacyUser?.user_id && !getCurrentUser()) {
    const legacyRequest = JSON.parse(localStorage.getItem("currentRequest"));
    save("currentUser", legacyUser);
    rememberDemoUser(legacyUser);
    if (legacyRequest?.user_id === legacyUser.user_id) save("currentRequest", legacyRequest);
  }
} catch { /* Storage may be unavailable; the in-memory fallback still works. */ }

// There is no account service, so the user (name + generated ID) only lives in this browser.
// "Register" in the UI means registering for the sale (waiting room /submit), as in the slides.
// user: { name, user_id }. Names may repeat; the generated UUID is the identity.
function getCurrentUser() {
  return load("currentUser");
}

async function registerUser(name) {
  return withBrowserLock("identity", async () => {
    const existing = getCurrentUser();
    if (existing) return existing;
    const user = await window.createBrowserIdentity?.(name) || { name, user_id: crypto.randomUUID() };
    save("currentUser", user);
    rememberDemoUser(user);
    save("currentRequest", null);
    renderHeader();
    return user;
  });
}

// request: the waiting-room record, at least { request_id, user_id, section, party_size }.
function getCurrentRequest() {
  const request = load("currentRequest");
  return request?.user_id === getCurrentUser()?.user_id ? request : null;
}

function selectDemoIdentity(user, request = null) {
  window.stopBooking?.();
  save("currentUser", user);
  if (user) {
    rememberDemoUser(user);
    if (request) setCurrentRequest(request);
  }
  renderHeader();
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
  document.getElementById("current-user-id").textContent = user ? `User ID: ${user.user_id}` : "";
  document.getElementById("switch-user").hidden = !user;
}

document.getElementById("switch-user").addEventListener("click", () => {
  showTab("join");
  document.getElementById("demo-user-select").focus();
});

// Same-user tabs refresh their shared request. Selecting a different user or
// view in another tab never replaces this tab's session selection.
window.addEventListener("storage", (event) => {
  if (event.key === "demoUsers") window.renderDemoUserOptions?.();
  const requestKey = storageKey("currentRequest");
  if (![requestKey, null].includes(event.key)) return;
  delete memory[requestKey];
  volatileKeys.delete(requestKey);
  renderHeader();
  if (document.getElementById("join").classList.contains("active")) renderJoin();
});

renderHeader();

// Run the first tab's handler once every tab file has registered.
window.addEventListener("DOMContentLoaded", async () => {
  try { await window.initializeAccess?.(); }
  catch(error) {
    document.getElementById('demo-user-message').innerHTML=message(error.message,true);
    showTab('join');
    return;
  }
  const tab = load("currentTab");
  showTab(["admin", "batches", "seats", "join"].includes(tab)
    ? tab : document.querySelector("#tabs button.active").dataset.tab);
});
