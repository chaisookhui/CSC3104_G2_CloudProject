
/*
 * Admin Seat Map
 *
 * Displays live seat availability from the existing Seat Store API.
 * This page is read-only: it never reserves, confirms or cancels seats.
 */

(() => {
  "use strict";

  const SECTIONS = ["A", "B", "C", "D"];
  const REFRESH_INTERVAL_MS = 5000;

  const mapElement = document.getElementById("seat-map-content");
  const summaryElement = document.getElementById("seat-map-summary");
  const statusElement = document.getElementById("seat-map-status");
  const refreshButton = document.getElementById("refresh-seats");

  let refreshTimer = null;
  let refreshInProgress = false;

  // Group seats by their row, preserving the order from the Seat Store.
  function groupSeatsByRow(seats) {
    const rows = new Map();

    for (const seat of seats) {
      const row = String(seat.row);

      if (!rows.has(row)) {
        rows.set(row, []);
      }

      rows.get(row).push(seat);
    }

    for (const rowSeats of rows.values()) {
      rowSeats.sort(
        (a, b) =>
          Number(a.position_in_row) - Number(b.position_in_row)
      );
    }

    return rows;
  }

  // Only known seat states receive status styling.
  function seatState(state) {
    const normalized = String(state || "").toUpperCase();

    if (["AVAILABLE", "HELD", "CONFIRMED"].includes(normalized)) {
      return normalized;
    }

    return "UNKNOWN";
  }

  function countStates(seats) {
    const counts = {
      AVAILABLE: 0,
      HELD: 0,
      CONFIRMED: 0,
      UNKNOWN: 0
    };

    for (const seat of seats) {
      counts[seatState(seat.state)]++;
    }

    return counts;
  }

  // Render one section, including its rows and seats.
  function renderSection(section, seats) {
    const rows = groupSeatsByRow(seats);
    const counts = countStates(seats);

    const rowHtml = [...rows.entries()].map(([row, rowSeats]) => {
      const seatsHtml = rowSeats.map((seat) => {
        const state = seatState(seat.state);
        const label = seat.seat_id || seat.position_in_row;

        const tooltip = `${seat.seat_id || "Seat"} - ${state}`;

        return `
          <div
            class="map-seat map-seat--${state.toLowerCase()}"
            title="${esc(tooltip)}"
            aria-label="${esc(tooltip)}"
          >
            ${esc(label)}
          </div>
        `;
      }).join("");

      return `
        <div class="map-row">
          <span class="map-row-label">Row ${esc(row)}</span>
          <div class="map-row-seats">${seatsHtml}</div>
        </div>
      `;
    }).join("");

    return `
      <article class="map-section">
        <div class="map-section-header">
          <h3>Section ${esc(section)}</h3>
          <span class="muted">${seats.length} seats</span>
        </div>

        <div class="map-section-stats">
          <span>${counts.AVAILABLE} available</span>
          <span>${counts.HELD} held</span>
          <span>${counts.CONFIRMED} confirmed</span>
        </div>

        <div class="map-section-rows">
          ${rowHtml || '<p class="muted">No seats found.</p>'}
        </div>
      </article>
    `;
  }

  // Fetch all sections concurrently.
  async function refreshSeatMap() {
    if (refreshInProgress) {
      return;
    }

    refreshInProgress = true;
    refreshButton.disabled = true;
    statusElement.textContent = "Refreshing seats...";

    try {
      const results = await Promise.all(
        SECTIONS.map(async (section) => ({
          section,
          seats: await api(`seats/seats/${section}`)
        }))
      );

      const totals = {
        AVAILABLE: 0,
        HELD: 0,
        CONFIRMED: 0
      };

      for (const result of results) {
        const counts = countStates(result.seats);

        totals.AVAILABLE += counts.AVAILABLE;
        totals.HELD += counts.HELD;
        totals.CONFIRMED += counts.CONFIRMED;
      }

      const totalSeats = results.reduce(
        (sum, result) => sum + result.seats.length,
        0
      );

      summaryElement.innerHTML = `
        <div class="stat">
          <span>Total seats</span>
          <b>${totalSeats}</b>
        </div>
        <div class="stat">
          <span>Available</span>
          <b>${totals.AVAILABLE}</b>
        </div>
        <div class="stat">
          <span>Held</span>
          <b>${totals.HELD}</b>
        </div>
        <div class="stat">
          <span>Confirmed</span>
          <b>${totals.CONFIRMED}</b>
        </div>
      `;

      mapElement.innerHTML = results
        .map((result) => renderSection(result.section, result.seats))
        .join("");

      statusElement.textContent =
        `Last updated: ${new Date().toLocaleTimeString()}`;

    } catch (error) {
      statusElement.textContent = "Unable to refresh seat map.";

      // Preserve the previous successful map during temporary failures.
      if (!mapElement.children.length) {
        mapElement.innerHTML = message(
          `Could not load seats: ${error.message}`,
          true
        );
      }

      console.error("Seat Map refresh failed:", error);

    } finally {
      refreshInProgress = false;
      refreshButton.disabled = false;
    }
  }

  // Poll only when the Seat Map tab is visible.
  function startSeatMap() {
    if (refreshTimer !== null) {
      clearInterval(refreshTimer);
    }

    refreshSeatMap();

    refreshTimer = setInterval(() => {
      const tab = document.getElementById("seats");

      if (tab.classList.contains("active") && !document.hidden) {
        refreshSeatMap();
      } else if (!tab.classList.contains("active")) {
        clearInterval(refreshTimer);
        refreshTimer = null;
      }
    }, REFRESH_INTERVAL_MS);
  }

  refreshButton.addEventListener("click", refreshSeatMap);

  // app.js calls this whenever the Seat Map tab is opened.
  onTabOpen("seats", startSeatMap);
})();
