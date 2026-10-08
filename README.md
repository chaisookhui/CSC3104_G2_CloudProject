# CSC3104 Group 2: Fair Seat Allocation

Current stage: minimal Python setup with a Flask `/health` endpoint. Booking
features are not implemented yet. PostgreSQL is not needed for this setup.

## Windows PowerShell setup

Use Python **3.14.3** (64-bit), available as `python` on PATH. The supported
version is also recorded in `.python-version`; that file does not install Python.
Use one dependency workflow: Python `venv` and `pip` with the exact versions in
`requirements.txt`. No global package installation or environment activation is
needed.

```powershell
Set-Location C:\Users\Hp\Documents\GitHub\CSC3104_G2_CloudProject
python --version
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

## Run locally

```powershell
.\.venv\Scripts\python.exe -m flask --app app:create_app run --host 127.0.0.1 --port 5000
```

In a second PowerShell window:

```powershell
Invoke-RestMethod http://127.0.0.1:5000/health
```

Expected response: `status` is `ok`. Stop the server with Ctrl+C. This is Flask's
local development server; choose a production server when deployment is added.

When intentionally updating dependencies, install the selected versions into a
clean `.venv`, then regenerate the complete pins:

```powershell
.\.venv\Scripts\python.exe -m pip freeze | Set-Content -Encoding ascii requirements.txt
```

Existing `src/**/placeholder.txt` files are unused scaffolding and candidates for
later removal by the team. They are preserved here.
