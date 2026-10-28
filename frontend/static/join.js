// User > My booking: enter a name, then register for the sale (waiting room POST /submit).
// Once registered, the booking status from booking.js appears below in the same tab.

function renderJoin() {
  const user = getCurrentUser();
  const request = getCurrentRequest();
  document.getElementById("register-step").hidden = Boolean(user);
  // One active request per user: once joined, show the booking instead of the form.
  document.getElementById("join-step").hidden = !user || Boolean(request);
  document.getElementById("booking-step").hidden = !request;
  document.getElementById("join-result").innerHTML = "";
  if (user) {
    document.getElementById("join-greeting").textContent = `Hi ${user.name}, choose your section and party size.`;
  }
  if (request) trackBooking(request.request_id);
  else stopBooking();
}

document.getElementById("register-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const name = new FormData(event.target).get("name").trim();
  if (!name) return;
  registerUser(name);
  event.target.reset();
  renderJoin();
});

document.getElementById("join-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  try {
    const request = await api("waiting-room/submit", {
      user_id: getCurrentUser().user_id,
      section: form.get("section"),
      party_size: Number(form.get("party_size")),
    });
    setCurrentRequest(request);
    renderJoin();
  } catch (error) {
    document.getElementById("join-result").innerHTML = message(error.message, true);
  }
});

onTabOpen("join", renderJoin);
