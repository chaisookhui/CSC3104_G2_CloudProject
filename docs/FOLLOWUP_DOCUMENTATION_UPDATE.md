# Follow-up documentation synchronization

19 November 2026 (Singapore). Documentation-only update using completed evidence.
No application test, deployment, lab reset, image rebuild, commit or push occurred.

The detailed analysis and evidence index were updated when testing finished. The
main submission PDFs still described the earlier November 14 baseline. They now
include the latest findings as labelled supplements, retaining the original results.

## Current submission documents

- Results report PDF/Markdown: **26 PDF pages**. Original baseline on pages 1-22;
  latest summary/capacity/bursts on page 23, paired scheduler analysis page 24,
  fresh HPA overview page 25, and traffic/HTTP/delivery figure page 26. Pages 25-26
  are landscape for legibility.
- Instructions PDF/Markdown: **27 PDF pages**. Original baseline on pages 1-26;
  latest measured findings on page 27.
  Quick Start remains page 2, demonstration route page 3, and matrices pages 23-24.
- Project/testing READMEs, scaling/robustness/validation guides and evidence index:
  latest measured-results notices and links, mixed capacity findings and resume
  guidance. Existing procedures/history remain present.
- Historical submission/guide verification and evaluation-plan documents: links
  to later measured evidence and this current verification record. Original dated
  findings remain historical, including their earlier page counts/package hashes.

The instruction supplement source is `docs/FOLLOWUP_TESTING_APPENDIX.md`.
`experiments/refresh_followup_documents.py` rebuilds the current documents from
audited follow-up summaries/figures and the preserved original report PDF. The
old combined-report builder was not invoked; deleted combined/handbook files
were not recreated.

## Findings synchronized

All 64 planned units are COMPLETE: 30 scheduler pairs, four HPA cycles, 21 capacity
trials and nine bursts. COMPLETE is separate from outcome. All 60 scheduler
replays passed correctness checks; F3's rate gap worsened despite higher Jain.
All four full HPA cycles and all nine bursts passed their recorded checks.
All 27,900 burst offers were accepted and terminally processed within 600s.

Capacity remains mixed: 14 workload PASS, seven INCONCLUSIVE, 19 valid-delivery
results and two invalid-delivery results; eight composite-SLO passes. Highest
observed passes at API1/2/4 were 200/250/250 requests/s with 3/3, 1/3 and 1/3
passing trials at those points. All five complete 300/s attempts remain
INCONCLUSIVE; unreconciled ACKs are lower bounds. Invalid delivery does not
establish capacity, and P95 alone cannot establish an SLO pass.

The saved-data audit passed 1,046 checks with zero failures. Historical
interruptions remain retained; no planned trial remains pending. The current
documents do not make production-capacity or general fairness-superiority claims.

## Verification and preservation

Text extraction confirmed the original baseline pages retain their original text.
Every added page and both cover notices were rendered to PNG and visually
inspected for clipping, overflow, table alignment and figure legibility.

Before-edit copies of 19 existing documents and their hashes are in
`output/validation/followup-20261119/document-refresh/before/` and `before.json`.
Current file hashes and checks are in `document-refresh/verification.json`.
The user's existing edits and the original 25-case evidence remain preserved.

The sealed `GROUP02_Followup_Final_20261119.zip` remains unchanged, SHA256
`de339c1c913baa25a785e987ba7c90991474089fa7e282f111eb58c0540a42b7`.
It predates this document refresh. Supply the current PDFs alongside it; existing
reviewer archives were not silently republished or recreated.

Article table/paragraph and PNG/SVG slide assets remain in the follow-up report
folder. This refresh does not edit a separate article manuscript or slide deck.
