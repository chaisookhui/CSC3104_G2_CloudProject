// Tab switching, plus the registered user and their current request shared by every tab.

const tabHandlers = {};

// A tab file calls onTabOpen("seats", fn) to run fn each time that tab is shown.
function onTabOpen(tab, handler) {
  tabHandlers[tab] = handler;
}

function showTab(tab) {
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

function load(key) {
  try {
    return JSON.parse(localStorage.getItem(key)) ?? memory[key] ?? null;
  } catch {
    return memory[key] ?? null;
  }
}

function save(key, value) {
  memory[key] = value;
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Memory copy is enough for this page.
  }
}

// There is no account service, so the user (name + generated ID) only lives in this browser.
// "Register" in the UI means registering for the sale (waiting room /submit), as in the slides.
// user: { name, user_id }. The user_id gets a random suffix so names can repeat.
function getCurrentUser() {
  return load("currentUser");
}

function registerUser(name) {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "user";
  const user = { name, user_id: `${slug}-${Math.random().toString(36).slice(2, 6)}` };
  save("currentUser", user);
  save("currentRequest", null);
  renderHeader();
  return user;
}

// request: the waiting-room record, at least { request_id, user_id, section, party_size }.
function getCurrentRequest() {
  return load("currentRequest");
}

function setCurrentRequest(request) {
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

document.getElementById("switch-user").addEventListener("click", () => {
  save("currentUser", null);
  save("currentRequest", null);
  renderHeader();
  showTab("join");
});

renderHeader();

// Run the first tab's handler once every tab file has registered.
window.addEventListener("DOMContentLoaded", () =>
  showTab(document.querySelector("#tabs button.active").dataset.tab));
