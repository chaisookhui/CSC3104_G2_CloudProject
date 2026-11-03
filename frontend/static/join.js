// User > My booking: enter a name, then register for the sale (waiting room POST /submit).
// Once registered, the booking status from booking.js appears below in the same tab.

function renderJoin() {
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
  await registerUser(name);
  event.target.reset();
  renderJoin();
});

let joining = false;
async function submitRegistration(payload) {
  if (joining) return;
  joining = true;
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
    document.getElementById("join-result").innerHTML = message(
      "Registration could not be verified. Retry or reload to recover the same request. " + error.message, true);
  } finally {
    joining = false;
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

onTabOpen("join", renderJoin);

window.addEventListener("online", () => {
  const user = getCurrentUser();
  if (user && !getCurrentRequest() && document.getElementById("join").classList.contains("active")) {
    const pending = load("registration:" + user.user_id);
    if (pending) submitRegistration(pending);
  }
});
