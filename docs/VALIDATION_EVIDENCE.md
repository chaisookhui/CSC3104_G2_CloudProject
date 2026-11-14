# Validation evidence and submission files

The recorded final local validation covers all 25 documented case IDs: 15 newly
completed functional/browser/deployment cases and 10 full-scope final v9 cases
independently re-audited with unchanged application/configuration sources and
matching captured image IDs. The independent audit passed 77 new checks and
244 original-workload raw checks (321 total), with zero failed audit checks.
These are bounded local results, not a guarantee on another machine.

## Version-controlled submission documents

- [Testing instructions](../output/pdf/GROUP02_INSTRUCTIONS.pdf) and
  [editable source](../output/pdf/GROUP02_INSTRUCTIONS.md): deployment, all 25
  acceptance procedures and the matching final evidence scope.
- [Current results and concepts report](../output/pdf/GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf)
  and [editable source](../output/pdf/GROUP02_Test_Results_and_Distributed_Concepts_Report.md):
  the current 25-case results, measurements, graphs and interpretation limits.
- [Combined results](../output/pdf/GROUP02_Combined_Test_Results.pdf): the same
  current results followed by the two original reports as historical appendices.
  Original failed/inconclusive attempts retain their original status.

## Separate raw evidence and reviewer packages

Generated artifacts are kept on disk and excluded from Git. Share these files
separately with the reviewer; excluding them from Git does not delete them.

| Local location | Contents |
|---|---|
| `output/review-package/GROUP02_Latest_Source.zip` | Current public working-source snapshot, including uncommitted fixes when generated |
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

- [Exact performance/HPA studies](../experiments/SCALING_STUDIES.md)
- [Final functional/browser verification and audit workflow](../experiments/EXAMINER_VERIFICATION.md)
- [Public v9 saved-data auditor](../experiments/audit_v9_evidence.py)

The application, testing tools, tests, dependency files, deployment manifests
and selected final documents belong in the source commit. Generated raw runs,
logs, reviewer ZIPs, private credentials/profiles, temporary page renders and
local chat checkpoints are excluded by `.gitignore`. Previously tracked
historical evidence is preserved; this cleanup does not untrack or delete it.
