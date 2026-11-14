# Final documentation and submission verification

**Earlier verification snapshot:** this report records the completed submission
synchronisation of the previous 23-page guide. Its original findings are retained
below. The later 26-page examiner edition and refreshed package checks are in
[EXAMINER_GUIDE_VERIFICATION.md](EXAMINER_GUIDE_VERIFICATION.md). Use current
package manifests/checksums for the latest guide; the application/evidence scope
is unchanged.

Prepared 14 November 2026. Scope: documentation synchronisation, saved-evidence
re-audit and release packaging. **No application tests were rerun, no deployment
was changed, and no Git commit or push was performed.**

## Verified source and evidence

The working tree was clean before this task, at
`253a6e27a78d34aa634b92a7f724eb42166c24dc` on `twy`. The application is already
committed there. Its 96 application/configuration files compared by the existing
v9 continuity auditor still match the captured final v9 build. This release
adds documentation and packaging changes over that commit; it does not claim
that the earlier experiments were executed at a newly created commit.

The authoritative ledger remains `output/validation/all25/all25-audit.json`:
all 25 distinct documented cases passed their recorded local acceptance
conditions. TC-01 to TC-13, TC-17 and TC-25 have new final-version evidence;
TC-14/15/16/18/19/20/21/22/23/24 retain their complete final v9 studies,
independently re-audited. The existing saved-data auditors were run again into
a new verification directory: **77 new checks plus 244 original-workload checks
passed, zero failed**. Their check results agree with the existing ledger.
These 321 checks are distinct from the 25 case IDs and earlier host/SQL tests.

Initial TC-09/13 checker failures, the TC-13 browser-bootstrap failure and earlier
incomplete HPA attempts remain preserved with their original status. Only the
completed passing cohorts support the final selected results. The results
report and combined report were verified and retained byte-for-byte.

## A. Files changed and purpose

All paths below are relative to the repository root.

| File | Reason |
|---|---|
| `README.md` | Point to the final 25-case evidence and this submission verification. |
| `TESTING.md` | Replace superseded coverage, ownership, timing and HPA summaries; retain broader production limitations and all procedure commands. |
| `CONTAINERS.md` | Link deployment instructions to the current local acceptance scope. |
| `infra/k8s/README.md` | Link Kubernetes instructions to the final evidence; retain local/HA limits. |
| `experiments/README.md` | Correct current-result links and distinguish the 12 November record from final results. |
| `experiments/ROBUSTNESS.md` | Identify final case evidence and explicitly label the earlier incomplete HPA record historical. |
| `experiments/VALIDATION.md` | Label the 12 November 18-procedure revision historical; direct readers to the final 25-case ledger. |
| `experiments/EXAMINER_VERIFICATION.md` | Describe the completed 15-case verification and explain reproduction without implying it remains missing. |
| `experiments/SCALING_STUDIES.md` | Connect unchanged study procedures to the final v9 results and their limits. |
| `evaluation/ARCHITECTURE_AUDIT.md` | Label the 8 November assessment historical rather than current acceptance status. |
| `evaluation/EVALUATION_MATRIX.md` | Label the earlier research plan historical and separate extensions from the 25-case suite. |
| `docs/VALIDATION_EVIDENCE.md` | Update committed-source/package provenance and link this verification. |
| `docs/FINAL_SUBMISSION_VERIFICATION.md` | Add this final verification report. |
| `output/pdf/README.md` | Identify the current guide/results and clearly mark the older 30-case handbook as archived. |
| `output/pdf/GROUP02_INSTRUCTIONS.md` | Add current submission revision and documentation-only scope; retain final coverage and complete procedures. |
| `output/pdf/GROUP02_INSTRUCTIONS.pdf` | Regenerate the 23-page guide with the existing unchanged renderer and inspect every rendered page. |
| `experiments/package_review.py` | Correct release provenance, retain historical-verification context, and support source-only documentation refreshes while preserving verified results bundles. This is release tooling, not an application/test change. |

Regenerated ignored deliverables under `output/review-package/`:
`GROUP02_Latest_Source.zip`, `GROUP02_Raw_Results_and_Graphs.zip`,
`GROUP02_Graphs_and_CSV.zip`, `START_HERE.md`, `package-verification.json`
and `SHA256SUMS.txt`. The earlier versions of these six files were copied to
`output/review-package/releases/pre-sync-20261114-210127/` before regeneration.
Their existing checksums remain available there. No sealed evidence archive
was overwritten.

New local verification records are under
`.local/submission-verification/20261114-210127/`: the pre-edit `baseline.json`,
saved-evidence re-audit output, `verification.json` and the verification utility.
They are excluded from Git and are separate from the existing experimental
results. Temporary PDF renders are under `tmp/pdfs/final-submission-sync/`.

## B. Inconsistencies identified and corrected

| Finding | Resolution |
|---|---|
| External review said the source ZIP still contained the guide with 15 incomplete cases. | Actual inspection found the corrected 23-page guide already in the repository and latest ZIP. Its existing 25-case status was retained; this task adds submission provenance and regenerates the PDF. No unsupported status was changed to PASS. |
| Several current-result links still selected `robustness-results.md` from 12 November. | Current links now select the final report/evidence index; older records remain explicitly historical. |
| `experiments/VALIDATION.md` called the 18-procedure revision current. | That section is explicitly historical; the current guide has 25 cases. |
| The longer technical plan said local browser/admin ownership, detailed timing and complete HPA evidence still needed implementation. | Completed local mechanisms/results are identified; verified accounts, public security, header forwarding, HA and other broader work remain limitations. |
| Earlier architecture/research documents could be mistaken for the final status. | Their original findings are retained under an explicit historical notice and a link to current evidence. |
| Package instructions described already-committed fixes as uncommitted. | Provenance records the actual base commit, actual Git status, matching v9 application and documentation/release overlay. |
| Archived handbook and verification hashes could be mistaken for current files. | The PDF index identifies the archived handbook. Package START_HERE explains that old verification hashes describe historical versions; new manifests hash the current guide. |

## C. Non-destructive verification results

| Required check | Outcome | Supporting verification |
|---|---|---|
| Final instructions PDF updated | PASS | Rebuilt with existing `build_instructions.py`; 23 pages; all pages rendered and visually inspected. |
| Markdown and PDF consistent | PASS | Current revision/scope and all 25 case IDs present in extracted PDF text; commands and expected-result lines unchanged from the pre-edit guide. |
| Outdated coverage statements corrected | PASS | Current documentation points to final evidence; older studies and the archived handbook explicitly labelled historical. |
| All 25 cases accurately referenced | PASS | Exactly TC-01 through TC-25 selected PASS in the unchanged ledger, with the correct 15/10 evidence split. |
| Final test results match the evidence ledger | PASS | Existing auditors reproduced the same 77 and 244 passing checks; report matrix matches all 25 ledger IDs; result PDFs unchanged. |
| Application source unchanged | PASS | All 198 protected non-document source/test/configuration files match the pre-edit SHA-256 baseline; v9 comparison also matches all 96 recorded files. |
| Test scripts unchanged | PASS | Protected test and experiment files match baseline; no assertions, workload settings, seeds or thresholds changed. Only release packaging tooling changed. |
| Raw experimental results unchanged | PASS | All 4,397 pre-existing raw/evidence/graph files match baseline, including both sealed evidence archives and existing verification records. |
| Source package integrity verified | PASS | ZIP CRC, per-entry SHA-256 manifests, repository-byte comparisons, required deployment/test/document files and current guide checked. Results/graph data compared with previous packages. |
| No sensitive credentials packaged | PASS | Private-path exclusions and scans for locally configured credentials, derived operator/admin credentials and private-key material passed for all three packages. Public credential templates remain intentional. |

Machine-readable details: local `verification.json` and
`output/review-package/package-verification.json`. Current release SHA-256 values
are in `output/review-package/SHA256SUMS.txt`; they are kept outside this report
to avoid a self-referential source-package hash. The final source archive includes
this report, the current guide and a complete source manifest.

## D. Final deliverables and use

- Corrected guide: `output/pdf/GROUP02_INSTRUCTIONS.pdf`; editable source beside it.
- Final results: `output/pdf/GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf`.
- Current results plus historical appendices: `output/pdf/GROUP02_Combined_Test_Results.pdf`.
- Application, deployment/test tooling and current documentation: `output/review-package/GROUP02_Latest_Source.zip`.
- Recorded evidence and figures: `output/review-package/GROUP02_Raw_Results_and_Graphs.zip`.
- Smaller figure/table bundle: `output/review-package/GROUP02_Graphs_and_CSV.zip`.
- Package usage/provenance and checksums: `output/review-package/START_HERE.md`, manifests inside each ZIP and `SHA256SUMS.txt`.

The source archive contains installation/execution instructions, dependencies,
application/frontend files, SQL migrations, tests, experiment tools, Dockerfiles
and Compose/Kubernetes manifests. Raw evidence is supplied separately. Extract
both larger archives into the same destination so the documented evidence paths
match. New installations generate their own credentials; do not copy private
local credential files or browser profiles.

## E. Remaining submission risks

- All PASS claims concern the recorded local single-node Kind/isolated Compose
  acceptance conditions. They do not guarantee another execution, production
  reliability, public security, storage HA, cloud-node failover or superior
  performance/fairness at arbitrary loads.
- Documentation/release changes remain uncommitted. If submitting a repository
  URL, commit/review these changes and verify that the submitted revision contains
  them. No remote CI result or remote branch update was claimed here.
- Reviewer ZIPs and raw evidence are intentionally ignored by Git. Supply those
  files separately when the examiner needs recorded data, and use the current
  checksums. Historical archives/handbooks are preserved for provenance, not as
  replacements for the current guide and report.
- This verifies the technical files requested. Any separate university research
  article, submission portal, naming, deadline or marking-rubric requirement must
  still be checked against the actual submission brief; this is not a grade or
  completeness guarantee for requirements not supplied in this request.
