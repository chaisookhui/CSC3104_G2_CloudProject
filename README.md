# CSC3104 Group 2 - Fair Seat Allocation

The project allocates adjacent seats to groups of 1-4 people through separate
waiting-room, allocation, seat-store, and waitlist/payment services.

Module 3 is implemented in [src/seat-store](src/seat-store/README.md).
It owns PostgreSQL-backed seat state, atomic party holds, confirmation, expiry,
and durable expiry callbacks. Other modules communicate with it over HTTP.

From the repository root, with Python 3.11+ installed and Docker Desktop running:

```powershell
.\src\seat-store\setup.ps1
.\src\seat-store\run.ps1
```

In another PowerShell window:

```powershell
Invoke-RestMethod http://127.0.0.1:5003/health
.\src\seat-store\test.ps1
```

See the module README for API examples, lifecycle decisions, integration
contracts, configuration, and expected test outcomes. Other service directories
on this branch are placeholders; their owners' implementations live on their
respective branches.
