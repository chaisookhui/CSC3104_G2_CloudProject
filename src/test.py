#!/usr/bin/env python3
"""Tiny live seat-map viewer for demos. Python standard library only.

It serves one HTML page and relays /api/seats/<section> to the seat store,
so the browser never makes a cross-origin request (no CORS setup needed and
no changes to any module).

Read-only: it only ever sends GET requests, so it cannot change any seat.

Usage (from any folder, seat store must already be running):
    python3 viewer.py
    open http://127.0.0.1:8000

Optional environment variables:
    SEAT_STORE_URL   default http://127.0.0.1:5003
    VIEWER_PORT      default 8000
"""
import json
import os
import re
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SEAT_STORE_URL = os.environ.get("SEAT_STORE_URL", "http://127.0.0.1:5003").rstrip("/")
PORT = int(os.environ.get("VIEWER_PORT", "8000"))

PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Live seat map</title>
<style>
  :root {
    --bg: #ffffff; --fg: #1f2933; --muted: #6b7785; --line: #d5dbe1;
    --free: #eef2f6; --free-border: #b9c3ce; --err: #b42318;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #14181d; --fg: #e6eaee; --muted: #93a0ad; --line: #2c343d;
      --free: #1d242c; --free-border: #46515d; --err: #ff8a80;
    }
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px; background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 16px; }
  .tabs { display: flex; gap: 8px; margin-bottom: 16px; }
  .tabs button {
    padding: 6px 16px; border: 1px solid var(--line); background: transparent;
    color: var(--fg); border-radius: 6px; cursor: pointer; font-size: 14px;
  }
  .tabs button.active { background: var(--fg); color: var(--bg); }
  .summary { display: flex; flex-wrap: wrap; gap: 20px; margin-bottom: 12px; font-size: 14px; }
  .summary b { font-size: 18px; }
  .next { color: var(--muted); font-size: 13px; margin-bottom: 14px; min-height: 18px; }
  #error { color: var(--err); font-size: 14px; margin-bottom: 12px; min-height: 20px; }
  .row { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
  .rowlabel { width: 56px; color: var(--muted); font-size: 12px; }
  .seat {
    width: 38px; height: 38px; border-radius: 6px; display: flex;
    align-items: center; justify-content: center; font-size: 12px;
    border: 2px solid var(--free-border); background: var(--free); color: var(--muted);
  }
  .seat.HELD { color: #fff; border-color: transparent; font-weight: 600; }
  .seat.CONFIRMED { color: #fff; border-color: var(--fg); font-weight: 700; }
  .seat.EXPIRED { border-style: dashed; opacity: 0.6; }
  .legend { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 18px; font-size: 12px; color: var(--muted); }
  .legend span { display: inline-flex; align-items: center; gap: 6px; }
  .chip { width: 14px; height: 14px; border-radius: 3px; display: inline-block; }
</style>
</head>
<body>
  <h1>Live seat map</h1>
  <div class="sub">Refreshes every second. Seats of the same party share a colour.</div>
  <div class="tabs" id="tabs"></div>
  <div class="summary" id="summary"></div>
  <div class="next" id="next"></div>
  <div id="error"></div>
  <div id="grid"></div>
  <div class="legend">
    <span><i class="chip" style="background:var(--free);border:2px solid var(--free-border)"></i>Available</span>
    <span><i class="chip" style="background:#4f8cff"></i>Held (colour = one party)</span>
    <span><i class="chip" style="background:#4f8cff;border:2px solid var(--fg)"></i>Confirmed (bold border)</span>
    <span><i class="chip" style="border:2px dashed var(--free-border)"></i>Expired</span>
  </div>

<script>
  const SECTIONS = ["A", "B", "C"];
  const PALETTE = ["#4f8cff", "#e8743b", "#2f9e77", "#a259e6", "#c99a06", "#d9486f", "#1fa7b8", "#7a8a1f"];
  const colours = {};
  let nextColour = 0;
  let current = "A";
  let busy = false;
  let lastSeats = [];

  function colourFor(id) {
    if (!(id in colours)) colours[id] = PALETTE[nextColour++ % PALETTE.length];
    return colours[id];
  }

  function parseTime(s) {
    // JS Date handles milliseconds; trim microseconds to be safe across browsers
    return Date.parse(String(s).replace(/(\.\d{3})\d+/, "$1"));
  }

  function renderTabs() {
    const box = document.getElementById("tabs");
    box.innerHTML = "";
    SECTIONS.forEach(function (s) {
      const b = document.createElement("button");
      b.textContent = "Section " + s;
      if (s === current) b.className = "active";
      b.onclick = function () { current = s; lastSeats = []; renderTabs(); refresh(); };
      box.appendChild(b);
    });
  }

  function render(seats) {
    const rows = {};
    const counts = { AVAILABLE: 0, HELD: 0, CONFIRMED: 0, EXPIRED: 0 };
    let soonest = null;
    const now = Date.now();

    seats.forEach(function (s) {
      (rows[s.row] = rows[s.row] || []).push(s);
      if (s.state in counts) counts[s.state]++;
      if (s.state === "HELD" && s.hold_expiry) {
        const t = parseTime(s.hold_expiry);
        if (!isNaN(t) && (soonest === null || t < soonest)) soonest = t;
      }
    });

    const total = seats.length;
    const used = counts.HELD + counts.CONFIRMED;
    const pct = total ? Math.round((used / total) * 100) : 0;
    document.getElementById("summary").innerHTML =
      "<div><b>" + counts.AVAILABLE + "</b> available</div>" +
      "<div><b>" + counts.HELD + "</b> held</div>" +
      "<div><b>" + counts.CONFIRMED + "</b> confirmed</div>" +
      "<div><b>" + pct + "%</b> filled (" + used + " / " + total + ")</div>";

    document.getElementById("next").textContent = soonest === null
      ? "No active holds."
      : "Next hold expires in " + Math.max(0, Math.round((soonest - now) / 1000)) + "s.";

    const grid = document.getElementById("grid");
    grid.innerHTML = "";
    Object.keys(rows).map(Number).sort(function (a, b) { return a - b; }).forEach(function (r) {
      const line = document.createElement("div");
      line.className = "row";
      const label = document.createElement("div");
      label.className = "rowlabel";
      label.textContent = "Row " + r;
      line.appendChild(label);
      rows[r].sort(function (a, b) { return a.position_in_row - b.position_in_row; }).forEach(function (s) {
        const d = document.createElement("div");
        d.className = "seat " + s.state;
        d.textContent = s.position_in_row;
        let tip = s.seat_id + " - " + s.state;
        if (s.held_by_request_id) {
          tip += "\n" + s.held_by_request_id;
          if (s.state === "HELD" || s.state === "CONFIRMED") d.style.background = colourFor(s.held_by_request_id);
        }
        if (s.state === "HELD" && s.hold_expiry) {
          const t = parseTime(s.hold_expiry);
          if (!isNaN(t)) tip += "\nexpires in " + Math.max(0, Math.round((t - now) / 1000)) + "s";
        }
        d.title = tip;
        line.appendChild(d);
      });
      grid.appendChild(line);
    });
  }

  async function refresh() {
    if (busy) return;
    busy = true;
    const err = document.getElementById("error");
    try {
      const resp = await fetch("/api/seats/" + encodeURIComponent(current), { cache: "no-store" });
      const data = await resp.json();
      if (!resp.ok || !Array.isArray(data)) {
        throw new Error((data && data.error) || ("HTTP " + resp.status));
      }
      lastSeats = data;
      err.textContent = "";
      render(data);
    } catch (e) {
      err.textContent = "Cannot load Section " + current + ": " + e.message;
      if (lastSeats.length) render(lastSeats);
    } finally {
      busy = false;
    }
  }

  renderTabs();
  refresh();
  setInterval(refresh, 1000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path in ("/", "/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
            return

        match = re.fullmatch(r"/api/seats/([A-Za-z0-9_-]{1,20})", path)
        if match:
            url = f"{SEAT_STORE_URL}/seats/{match.group(1)}"
            try:
                with urllib.request.urlopen(url, timeout=3) as resp:
                    self._send(resp.status, resp.read(), "application/json")
            except urllib.error.HTTPError as exc:
                msg = {"error": f"seat store returned HTTP {exc.code}"}
                self._send(exc.code, json.dumps(msg), "application/json")
            except Exception:
                msg = {"error": f"cannot reach seat store at {SEAT_STORE_URL}"}
                self._send(502, json.dumps(msg), "application/json")
            return

        self._send(404, "Not found", "text/plain; charset=utf-8")

    def log_message(self, fmt, *args):
        pass  # keep the demo terminal quiet


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Seat map viewer: http://127.0.0.1:{PORT}")
    print(f"Reading from seat store at {SEAT_STORE_URL} (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")