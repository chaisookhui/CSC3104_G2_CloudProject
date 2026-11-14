# Final-version functional verification and report merge

The new examiner harness fills the fifteen final-version coverage gaps in the
25-case instructions. It uses the existing lab setup, request plumbing, waits,
contention workload and original SQL invariants. Genuine Chromium form clicks,
reloads, separate tabs/profiles and browser-process restarts supplement HTTP and
database assertions. Mock payment expiry retains its original 300-second TTL.

The ten original full-scope v9 cases are independently re-audited from their raw
evidence, with unchanged application/configuration sources and deployed images.
They are not replaced by smaller test runs. Existing failures remain in place.

## Run the missing cases

This command explicitly erases ONLY `csc3104-lab`. Export existing lab evidence
first. Use a new run ID and run one workload at a time. It does not reset main.
TC-09 uses a separate Compose project and loopback18280, then stops only that
project with its volumes retained.

```powershell
python experiments/examiner_verify.py --reset-lab --run examiner-new-run
```

Prerequisites: current application images built/loaded, working Docker/Kind,
Python with the existing load dependencies, Node.js, Playwright and an installed
Chrome or Edge. The local authoring environment uses bundled Node/Playwright;
on another workstation override `EXAM_NODE`, `EXAM_PLAYWRIGHT` (resolvable module
name or package path), and optionally `EXAM_BROWSER` (installed browser exe).
No browser is downloaded by this harness. The normal manual examiner route in
GROUP02_INSTRUCTIONS.pdf does not require this browser automation setup.

Each script run also needs the original final-v9 source inventory and baseline
snapshot for continuity comparison. Extract the separately supplied v9 evidence
ZIP to the repository root before using this combined-evidence workflow on
another machine. A plain checkout without the evidence is not a completed
verification; do not bypass that check to claim the earlier results.

Use `--only` with a fresh ID to rerun an unassessable case: journeys (TC01-04),
capacity (TC05), validation (TC06), flow (TC07), contention (TC08), compose
(TC09), replacement (TC10), payment-pause (TC11), allocation-pause (TC12),
seat-outage (TC13), storage (TC17), or browser (TC25). Original failed evidence
is never overwritten. A rerun must satisfy the same original acceptance checks.

Private browser profiles/cookies remain under `.local/examiner-browser-profiles/`.
Do not submit those directories. Exported JSON and screenshots contain only
synthetic test identities and observed application state, not login passwords.

## Audit and publish after successful completion

Supply all completed run IDs, including preliminary failed attempts and their
completed replacements, in chronological order:

```powershell
python experiments/examiner_audit.py --runs RUN_A RUN_B RUN_C --output output/validation/all25
```

This re-evaluates new raw evidence, re-executes the v9 saved-data auditor in
`experiments/audit_v9_evidence.py`
with a separate output directory, checks current application source continuity
and captured deployed image IDs, and requires all25 distinct test IDs. No new
traffic is generated. Its all25-audit.json identifies exactly which passing run
supports each case and preserves the preliminary failure ledger.

The report builder refuses publication unless the complete independent audit
passes. It preserves the original source PDFs/Markdown before editing, writes
the updated results/concepts report, and merges both original PDFs as explicitly
historical appendices after the current25-case report. Original inconclusive
attempts keep their original status. PDF skill authoring marker and full rendered
page QA are required when this is used in the authoring workflow.

```powershell
python experiments/build_all25_report.py --audit output/validation/all25/all25-audit.json
python experiments/export_examiner_evidence.py --audit output/validation/all25/all25-audit.json
```

Restore the ordinary lab after exporting the evidence:

```powershell
python experiments/run.py lab --reset-lab --hold-ttl 300 --batch-size 10
```

The new evidence ZIP contains the new functional/browser runs, selected raw
assertions, current reports and this workflow's source. It references the
previously sealed full v9 evidence ZIP by checksum; supply both for all raw
performance/fault data. It does not rewrite that older archive or its hashes.
