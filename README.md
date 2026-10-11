# CSC3104 Group 2 – Fair Seat Allocation

## About the Project

We are building a ticket booking system that allocates adjacent seats to groups of 1–4 people.

The system will support seat reservations, temporary holds, mock payments, expiry, and waitlists.

Our main goal is to develop and test the **Demand-Cycle allocation algorithm**, comparing its fairness and performance against other methods.

## Current Progress

The project is still in its early development stage.

- Flask application with a working `/health` endpoint.
- Basic project structure and dependencies are set up.
- Booking features, database, tests, and background workers are not implemented yet.
- PostgreSQL is not required for the current setup.

## Getting Started

**1. Install Python 3.14.3 (64-bit).**

**2. Open PowerShell in the project folder and run:**

```powershell
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

**3. Start the Flask application:**

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app run --host 127.0.0.1 --port 5000
```

**4. Open another PowerShell window and test:**

```powershell
Invoke-RestMethod http://127.0.0.1:5000/health
```

Expected response:

```json
{"status": "ok"}
```

Press `Ctrl+C` to stop the server.

## Project Files

| File / Folder | Purpose |
|---|---|
| `app.py` | Flask application |
| `requirements.txt` | Python dependencies |
| `.python-version` | Python version (3.14.3) |
| `.gitignore` | Excludes local and generated files |
| `src/` | Placeholder folders for future features |

## Notes

- The `/health` endpoint only confirms that Flask is running.
- The `src/` folders do not contain working features yet.
- Add new dependencies only when needed and update `requirements.txt`.
- Keep local `.venv/`, `.env`, and generated files out of Git.