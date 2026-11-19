# Which submission documents to use

Current documents include the **19 November 2026 follow-up**, preserving the
original **25-case baseline**. That baseline recorded 25 PASS cases and 321 audit
checks. The follow-up completed 64 units with mixed capacity outcomes; its saved-data
audit passed 1,046 checks with zero failures. COMPLETE is not PASS.

- `GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf` and `.md`: **26-page**
  results PDF. Original baseline pages 1-22; follow-up summary/capacity/bursts
  page 23, scheduler analysis page 24, HPA overview page 25, traffic/HTTP/delivery
  figure page 26. Figure pages 25-26 are landscape.
- `GROUP02_INSTRUCTIONS.pdf` and `.md`: **27-page** guide. Quick Start remains
  page 2, demonstration route page 3, and matrices pages 23-24. Appendix A on
  page 27 contains the latest measured findings.

[Detailed findings](../../docs/FOLLOWUP_EVALUATION_RESULTS.md),
[article material and figures](../validation/followup-20261119/report/), and the
[evidence index](../../docs/VALIDATION_EVIDENCE.md) provide supporting data.
Highest observed capacity passes at API1/2/4 were 200/250/250 requests/s, with
3/3, 1/3 and 1/3 passing trials. All nine bursts and four full HPA cycles passed.

## Editing and rebuilding

The report supplement uses audited JSON/figures and the preserved original report
PDF. The instruction supplement source is
[`docs/FOLLOWUP_TESTING_APPENDIX.md`](../../docs/FOLLOWUP_TESTING_APPENDIX.md).
With reportlab and pypdf available, run:

```powershell
python experiments/refresh_followup_documents.py
```

Keep the original 22-page report PDF under
`output/validation/followup-20261119/document-refresh/before/output/pdf/`.
The script retains those pages and appends the follow-up; it calls the existing
instructions renderer. Raw follow-up reports/audits/figures must be present.
Render and inspect PDF changes. The historical `build_all25_report.py` also
recreates a combined report and is not the current follow-up refresh command.
Deleted combined/handbook artifacts were not recreated.

## Version and archive boundaries

[Current document verification](../../docs/FOLLOWUP_DOCUMENTATION_UPDATE.md)
records page checks and current hashes. The older
[submission verification](../../docs/FINAL_SUBMISSION_VERIFICATION.md) and
[examiner-guide verification](../../docs/EXAMINER_GUIDE_VERIFICATION.md) remain
dated historical snapshots; their page counts and package hashes predate this refresh.

The final follow-up test ZIP and all earlier evidence/reviewer archives remain
sealed and unchanged. Supply current PDFs alongside the evidence ZIP for the
latest documentation. Current document hashes are in the separate document-refresh
manifest. No application test, deployment, image rebuild or new large archive was
performed for this documentation refresh.
