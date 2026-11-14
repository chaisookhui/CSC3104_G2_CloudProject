# Examiner-edition guide verification

14 November 2026. Documentation and release packaging only. No application test,
experiment, deployment, lab reset, Git commit or push was executed for this task.
The application remains at `253a6e27a78d34aa634b92a7f724eb42166c24dc`, with the
existing documentation/release overlay still uncommitted.

## A. Files modified in this task

The earlier task's uncommitted changes were present on entry and preserved.
This task changes only the following five public files:

| File | Change |
|---|---|
| `output/pdf/GROUP02_INSTRUCTIONS.md` | Add Quick Start and demonstration route; add methods/recorded-results companion; clarify TC-18 interpretation and Git history; number sections consistently; distinguish command effects. |
| `output/pdf/GROUP02_INSTRUCTIONS.pdf` | Regenerate the 26-page examiner edition using the existing unchanged renderer. |
| `output/pdf/README.md` | Update page count/navigation and point to this verification. |
| `docs/FINAL_SUBMISSION_VERIFICATION.md` | Add a notice identifying its original 23-page checks as an earlier snapshot; retain the original report below it. |
| `docs/EXAMINER_GUIDE_VERIFICATION.md` | Record this task's preservation, usability, PDF and packaging checks. |

Generated reviewer ZIPs, START_HERE, manifests and checksums under
`output/review-package/` are refreshed using existing `experiments/package_review.py`.
That script, the PDF renderer, application, runtime configurations, schemas,
tests and experiment scripts were not changed in this task.

## B. Examiner usability improvements

| Improvement | Outcome / location |
|---|---|
| One-page Quick Start | PASS: page 2, Section 1.1; prerequisites, verified startup commands/URLs, local administrator access, eight booking steps, isolated lab warning and evidence navigation. |
| Recommended demonstration route | PASS: page 3, Section 1.2; TC-01/08/10/21/24, methods, detailed references, saved evidence and lab effects. It explicitly requires suitable state between tests and does not replace the 25-case suite. |
| TC-24 review without rerun | PASS: route identifies saved HPA timelines/measurements and the full 18.5-minute minimum measured phases per target, plus setup/admission/collection time. |
| Usable 25-test matrix | PASS: pages 23-24, Sections 10/10.1; names, concepts and expected results are paired by Test ID with methods, dated recorded PASS and detailed verification/evidence references. |
| Expected versus observed | PASS: recorded results labelled 14 November 2026; explicit warning that recorded PASS is not a prediction or guarantee for independent execution. |
| TC-18 interpretation | PASS: page 15, Section 9.2; controlled correctness PASS separated from fairness/performance superiority; all six requested trade-offs explained. |
| Evidence navigation | PASS: Sections 9.7-9.9 retain detailed measurements, 15 new/10 v9 split, selected cohorts, original failures, environment and archive identifiers; concise navigation added. |
| Git provenance | PASS: historical uncommitted fixes distinguished from their inclusion in application commit 253a6e2; current documentation remains uncommitted. |
| Numbering and safety | PASS: unique numbered section/subsection headings, updated references, inspection/restart/stop/reset/main effects distinguished. No new destructive command was introduced. |

Startup/URLs were checked against `demo.py` and the Kubernetes launcher; UI
labels/behaviour against the frontend HTML/booking/checkout source, and local
password retrieval against `experiments/access.py`. No accounts or buttons were
invented. The lab-reset warning names deleted data and requires evidence export.

TC-18's qualitative direction was checked against the unchanged exported
`tc18-policy-seeds.csv` and `tc18-section-fairness.csv`, backed by the final F1
cohort. Demand-Cycle served more booking groups on average; FCFS had a higher
party-size fairness index. No new numeric claim or universal superiority was
added to the guide. Seeds, workloads, pass conditions and optional F2-F7 limits
remain unchanged.

## C. Preservation and non-destructive checks

| Check | Result |
|---|---|
| All 25 detailed tests and both 25-row summary tables present | PASS |
| Every original fenced command block preserved verbatim and in order | PASS; only the two existing startup commands are additionally repeated in Quick Start. |
| Objectives, preconditions, test data, expected-result and evidence/verification fields preserved | PASS; compared with the pre-edit Markdown snapshot. |
| Original expected-results matrix retained | PASS; all original case rows unchanged. |
| Section IDs unique and all numbered references resolve | PASS |
| Application, tests, schemas, Docker/Kubernetes runtime settings unchanged | PASS; protected-file hashes and v9 source continuity match. |
| Raw data, graphs, final results and historical verification unchanged | PASS; all 4,397 existing evidence/graph files match the prior baseline; original result PDFs and sealed archives unchanged. |
| Unrelated uncommitted changes preserved | PASS; all pre-existing public files outside the allowed documentation list match their entry hashes. |
| All 25 recorded results agree with final ledger | PASS; TC-01 through TC-25 remain PASS, 15 new cases plus 10 complete v9 cohorts. No new test outcome was generated. |

The previous 77 + 244 passing audit checks are preserved, not presented as a new
application execution. Original diagnostic failures and inconclusive studies
remain in the same files with the same hashes and statuses.

## D. PDF quality

The final PDF has **26 pages**. Every page was rendered and visually inspected.
Quick Start, demonstration tables and the methods/results matrix were also
reviewed at full size. No clipped/overlapping text, orphan-only page, broken table
or cut-off command was found. Fonts and table styles are the existing renderer's
sizes; they were not reduced to fit extra columns. Commands are kept together
and PDF bookmarks use the unique numbered headings.

## E. Submission packages

- Improved guide: `output/pdf/GROUP02_INSTRUCTIONS.pdf` and `.md`.
- Source: `output/review-package/GROUP02_Latest_Source.zip`.
- Raw evidence/current guide: `output/review-package/GROUP02_Raw_Results_and_Graphs.zip`.
- Figures/tables: `output/review-package/GROUP02_Graphs_and_CSV.zip`.
- Current checksums: `output/review-package/SHA256SUMS.txt`.
- Package checks: `output/review-package/package-verification.json`; per-file manifests inside each ZIP.

ZIP CRC and manifest hashes, source/repository byte equality and private-file /
configured-credential exclusions passed. The standalone and source/results ZIP
copies of both guide files are byte-identical. Only current guide/packaging
metadata changed in the results bundle; experimental data and graph files match
the prior packages. Sealed historical evidence ZIPs were never rewritten.

Earlier reviewer packages and their checksums were copied to
`output/review-package/releases/examiner-guide-20261114-213502/` before rebuilding.
New local baseline/check records are in
`.local/submission-verification/examiner-guide-20261114-213502/`. Earlier machine
verification records remain untouched. Package hashes are external to this
included report to avoid a self-referential source-ZIP checksum.

## F. Remaining issues and limits

No documentation or packaging check remains unverified. These changes were
verified statically and visually; new startup/browser/workload execution was
outside this documentation-only task. Recorded local acceptance does not
guarantee independent examiner results, production reliability, HA or public
security. New executions still need the documented tools, resources and evidence.

The documentation/release overlay remains uncommitted. Commit/review it before
submitting a repository URL; supply the ignored reviewer ZIPs separately if raw
recorded evidence is needed. University article/portal/marking requirements beyond
these requested technical artifacts were not assessed.
