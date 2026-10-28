"""Start a fresh local demo in one terminal: python demo.py

Starts Docker (PostgreSQL, seat-store, allocation), frees seats still held from the
last run, clears the dispatcher's saved batches, then runs the waiting room,
dispatcher and frontend with labelled logs. Ctrl+C stops all three. Local demo
helper only; Docker/Kubernetes deployments do not use it.
Options: --skip-docker (Docker services already running), --keep-seats,
--verbose (also show successful GET requests, which repeat every second),
--batch-size N (dispatcher batch size for this demo, 1-100; default 50).
"""
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
PY = sys.executable

DOCKER = [
    ["docker", "compose", "--env-file", "src/seat-store/.env", "-f", "src/seat-store/compose.yaml",
     "up", "-d", "postgres"],
    ["docker", "compose", "--env-file", "deploy/core/.env", "-f", "compose.core.yaml", "up", "-d"],
]
DOCKER_READY = {"seat-store": "http://127.0.0.1:5003/health", "allocation": "http://127.0.0.1:5002/ready"}

# (name, port, command, readiness URL). Started in this order.
SERVICES = [
    ("waiting-room", 5001, [PY, "src/services/waiting-room/app.py"], "http://127.0.0.1:5001/health"),
    ("dispatcher", 5005, [PY, "src/batch-dispatcher/app.py"], "http://127.0.0.1:5005/health"),
    # Checkout needs payment on 5004: add its entry here once that tab is built.
    ("frontend", 8080, [PY, "frontend/server.py"], "http://127.0.0.1:8080/"),
]


def step(text):
    print(f"\n== {text}", flush=True)


def fail(text):
    print(f"\nERROR: {text}", flush=True)
    sys.exit(1)


def wait_until_up(name, url, seconds=90):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if requests.get(url, timeout=2).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    fail(f"{name} did not become ready at {url}")


def batch_size():
    if "--batch-size" not in sys.argv:
        return None
    i = sys.argv.index("--batch-size")
    value = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
    # The allocator accepts batches of 1-100 parties.
    if not value.isdigit() or not 1 <= int(value) <= 100:
        fail("--batch-size needs a number from 1 to 100, e.g. --batch-size 10")
    return value


def port_in_use(port):
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_docker():
    step("Starting Docker services (PostgreSQL, seat-store, allocation)")
    for env_file in ("src/seat-store/.env", "deploy/core/.env"):
        if not (ROOT / env_file).exists():
            fail(f"{env_file} is missing. Follow CONTAINERS.md to create it first.")
    for command in DOCKER:
        try:
            if subprocess.run(command, cwd=ROOT).returncode != 0:
                fail("Docker command failed. Is Docker Desktop running?")
        except FileNotFoundError:
            fail("docker was not found. Install and start Docker Desktop.")
    for name, url in DOCKER_READY.items():
        wait_until_up(name, url)
    print("Docker services ready.")


def free_held_seats():
    # Cancelling releases a hold immediately; expiry would wait for its deadline.
    step("Freeing seats still held from the last run")
    freed = confirmed = 0
    for section in "ABCD":
        seats = requests.get(f"http://127.0.0.1:5003/seats/{section}", timeout=10).json()
        holds = {(s["held_by_request_id"], s["hold_id"]) for s in seats if s["state"] == "HELD"}
        confirmed += sum(s["state"] == "CONFIRMED" for s in seats)
        for request_id, hold_id in holds:
            response = requests.post("http://127.0.0.1:5003/seats/cancel", timeout=10,
                                     json={"request_id": request_id, "hold_id": hold_id})
            freed += response.ok
    print(f"Freed {freed} held parties.")
    if confirmed:
        print(f"{confirmed} paid (CONFIRMED) seats stay taken; seat-store has no way to free them.")


def clear_dispatcher():
    step("Clearing the dispatcher's saved batches")
    state = ROOT / ".local" / "dispatcher.sqlite3"
    if state.exists():
        state.unlink()
        print("Deleted .local/dispatcher.sqlite3")
    else:
        print("Nothing to clear.")


# Polling (dispatcher worker, open browser tabs) logs a successful GET every second.
QUIET = re.compile(r'"GET [^"]*" 200 ')


def stream(name, process, verbose):
    for line in process.stdout:
        if verbose or not QUIET.search(line):
            print(f"[{name}] {line}", end="", flush=True)


def interrupt(*_):
    raise KeyboardInterrupt


def stop(processes):
    for _, process in processes:
        if process.poll() is None:
            process.terminate()
    for _, process in processes:
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def main():
    # Stop cleanly on Ctrl+C or a terminate signal, including when started in the background.
    signal.signal(signal.SIGINT, interrupt)
    signal.signal(signal.SIGTERM, interrupt)
    size = batch_size()
    busy = [f"{name} ({port})" for name, port, _, _ in SERVICES if port_in_use(port)]
    if busy:
        fail("Already running: " + ", ".join(busy) + ". Stop those terminals first (Ctrl+C), then retry.")

    if "--skip-docker" in sys.argv:
        for name, url in DOCKER_READY.items():
            wait_until_up(name, url, seconds=5)
    else:
        start_docker()
    if "--keep-seats" not in sys.argv:
        free_held_seats()
    clear_dispatcher()

    step("Starting waiting room, dispatcher and frontend")
    env = dict(os.environ, PYTHONUNBUFFERED="1")
    if size:
        env["BATCH_SIZE"] = size  # Read by the dispatcher only.
        print(f"Dispatcher batch size: {size} (normal setting is 50)")
    processes = []
    try:
        for name, _, command, url in SERVICES:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                       errors="replace")
            processes.append((name, process))
            threading.Thread(target=stream, args=(name, process, "--verbose" in sys.argv),
                             daemon=True).start()
            wait_until_up(name, url, seconds=30)

        print("\n" + "=" * 52)
        print("  Demo ready: open http://127.0.0.1:8080")
        print("  Press Ctrl+C to stop. Run again for a fresh demo.")
        print("=" * 52 + "\n", flush=True)

        while True:
            for name, process in processes:
                if process.poll() is not None:
                    fail(f"{name} stopped unexpectedly; see its [{name}] lines above.")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        stop(processes)
        print("Stopped waiting room, dispatcher and frontend. Docker services keep running.")


if __name__ == "__main__":
    main()
