# Validation evidence and submission files

## Instructions, results and supporting evidence

The testing instructions explain **how to run the tests**. The results report
explains **what was observed and what it means**. Raw evidence provides the
underlying records used to check those findings: individual request measurements,
logs, screenshots, inventory snapshots and SQL checks. Audit files identify and
assess those records. A summary report does not replace its supporting evidence.

Download the attached `GROUP02_Submission.zip` from the
[submission release](https://github.com/chaisookhui/CSC3104_G2_CloudProject/releases/latest).
Extract it once and open `CSC3104_G2_CloudProject/START_HERE.md`. Most raw evidence
is distributed through this release attachment rather than the branch file listing.
The TC-14 export and a few earlier validation records are also committed to `twy`.

| Location inside the extracted project | Purpose |
|---|---|
| `output/pdf/` | The two readable submission reports and their editable sources. |
| `.local/test-results/` | Reviewed exported raw runs, including logs, observations and screenshots where collected. |
| `output/validation/all25/all25-audit.json` | Selects the recorded evidence folder supporting each of the 25 cases. |
| `output/validation/tc-fixes/` | Baseline performance/failure reports and audits. |
| `output/validation/followup-20261119/` | Follow-up reports, measurement tables and audits. |
| `output/tc14-extended-20261119/` | Extended TC-14 observations, summaries, charts and trial checks. |

The evidence paths in the guide are relative to this extracted project folder.
Opening recorded evidence does not run new tests or change a deployment.

The recorded final local validation covers all 25 documented case IDs: 15 newly
completed functional/browser/deployment cases and 10 full-scope final v9 cases
independently re-audited with unchanged application/configuration sources and
matching captured image IDs. The independent audit passed 77 new checks and
244 original-workload raw checks (321 total), with zero failed audit checks.
These are bounded local results, not a guarantee on another machine.

The application is committed in `253a6e2`; its 96 compared application/configuration
files match the recorded v9 build. Current release documentation and packaging
checks are recorded in [FINAL_SUBMISSION_VERIFICATION.md](FINAL_SUBMISSION_VERIFICATION.md).
These checks do not constitute a fresh application test run.

## Version-controlled submission documents

- [Testing instructions](../output/pdf/GROUP02_INSTRUCTIONS.pdf) and
  [editable source](../output/pdf/GROUP02_INSTRUCTIONS.md): deployment, all 25
  acceptance procedures and the matching final evidence scope.
- [Current results and concepts report](../output/pdf/GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf)
  and [editable source](../output/pdf/GROUP02_Test_Results_and_Distributed_Concepts_Report.md):
  the current 25-case results, measurements, graphs and interpretation limits.
- [Testing environment specifications](TESTING_ENVIRONMENT_SPECIFICATIONS.md):
  recorded CPU/memory availability, runtime versions, study configuration and
  the raw CSV/JSON evidence locations.

## Extended TC-14 seat-store baseline

The extended run `tc14-extended-20261119` completed five trials of 100 sequential measured holds each. All 500 succeeded, with zero failures or SQL invariant violations. The pooled median was 26.51 ms, P95 was 63.43 ms and P99 was 91.67 ms. The original three single-request TC-14 trials remain part of the 25-case acceptance record.

- Section 9, TC-14 of the [testing guide](../output/pdf/GROUP02_INSTRUCTIONS.pdf) contains the extended procedure. The TC-14 section of the [results report](../output/pdf/GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf) contains the per-trial table and both charts.
- [Methodology and interpretation](TC14_EXTENDED_RESULTS.md) explain the direct seat-store timing boundary and its limits for end-to-end booking.
- [Raw CSV](../output/tc14-extended-20261119/raw-observations.csv), [raw JSON](../output/tc14-extended-20261119/raw-observations.json) and [statistical summary](../output/tc14-extended-20261119/summary.json) are stored with trial-level deployment, inventory and SQL evidence in [the cohort export](../output/tc14-extended-20261119/). The raw files include all 550 observations, including 50 warm-ups.

## Complete submission package

Use `output/review-package/GROUP02_Submission.zip` for a single upload with source,
the two submission PDFs, baseline raw evidence and audit ledgers, historical reports,
the follow-up evidence and the extended TC-14 export. Extract it once
and open `CSC3104_G2_CloudProject/`; evidence paths in the guide are relative to that
folder. `START_HERE.md`, `SUBMISSION_MANIFEST.json` and
`SUBMISSION_VERIFICATION.json` explain and verify its contents.

For repository-URL submission, download the attached `GROUP02_Submission.zip` from
the [submission release](https://github.com/chaisookhui/CSC3104_G2_CloudProject/releases/latest).
GitHub's automatic source-code ZIP does not include ignored raw evidence.

Build with `python experiments/build_submission.py`. The builder uses the existing
reviewed evidence archives, checks their recorded hashes and does not copy private
`.local/` files wholesale. It verifies all 25 selected case folders and exports only
the two current submission PDFs. No application workloads are rerun.

## Earlier separate raw evidence and reviewer packages

Generated artifacts are kept on disk and excluded from Git. Share these files
separately with the reviewer; excluding them from Git does not delete them.

| Local location | Contents |
|---|---|
| `output/review-package/GROUP02_Latest_Source.zip` | Current public working-source snapshot; SOURCE_PROVENANCE.json identifies the base commit and any included documentation/release changes |
| `output/review-package/GROUP02_Raw_Results_and_Graphs.zip` | Raw JSON/CSV, traces, configuration/source/image fingerprints, logs, HPA timelines, audits and final/historical runs |
| `output/review-package/GROUP02_Graphs_and_CSV.zip` | Smaller PNG/SVG figure and CSV measurement bundle |
| `output/review-package/START_HERE.md` | Exact TC-16/18/23/24 run-folder and graph index |
| `output/review-package/SHA256SUMS.txt` and `package-verification.json` | Current package checksums and export verification |
| `output/validation/all25/all25-audit.json` | Case-by-case selected passing evidence and retained preliminary failure ledger |
| `output/validation/tc-fixes/` | Root causes, final performance report, original sealed evidence ZIP and raw-audit exports |
| `.local/test-results/` | Private original local run files; export reviewed/redacted copies rather than this directory wholesale |

The two earlier sealed evidence ZIPs under `output/validation/tc-fixes/` and
`output/validation/all25/` remain unchanged. The consolidated reviewer results
ZIP directly supplies their reviewed raw evidence plus current reports and
instructions. Preserve historical versions when assessing the original attempts.

Raw evidence is required to reproduce saved-data audits. Extract the reviewer
results ZIP into the checkout so its `.local/test-results/` and
`output/validation/` paths match. Source code alone is not a recorded test run.

## Reproduction tools

- [Exact performance/HPA studies](../experiments/STUDY_PROTOCOLS.md#scaling)
- [Final functional/browser verification and audit workflow](../experiments/README.md#examiner-verification)
- [Public v9 saved-data auditor](../experiments/audit_v9_evidence.py)

The application, testing tools, tests, dependency files, deployment manifests
and selected final documents belong in the source commit. Generated raw runs,
logs, reviewer ZIPs, private credentials/profiles, temporary page renders and
local chat checkpoints are excluded by `.gitignore`. Referenced historical
results remain available. Obsolete unreferenced authoring snapshots and screenshots
are excluded from the submission; local recovery copies are retained.

## Follow-up evaluation

[Follow-up results and evidence](FOLLOWUP_EVALUATION_RESULTS.md) record the
completed F2/F3/F6 scheduler comparisons, four full HPA cycles, higher-rate API
capacity trials and burst admission repetitions. They extend the original
25-case evidence separately, retaining mixed, inconclusive and interrupted
outcomes. The saved-data audit passed 1,046 checks with zero failures.

<!-- followup-20261119:current-documents:start -->
## Current document synchronization

The current reports integrate follow-up studies into TC-18, TC-19, TC-23 and TC-24, and the extended baseline into TC-14. The [document index](../output/pdf/README.md) lists the two PDFs. Use the complete submission release for the current documents and their evidence; earlier sealed archives remain provenance inputs.
<!-- followup-20261119:current-documents:end -->
