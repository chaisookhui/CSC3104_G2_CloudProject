# Which submission documents to use

Current documents include the **19 November 2026 follow-up** and the **extended TC-14 baseline**, preserving the
original **25-case baseline**. That baseline recorded 25 PASS cases and 321 audit
checks. The follow-up completed 64 units with mixed capacity outcomes; its saved-data
audit passed 1,046 checks with zero failures. COMPLETE is not PASS.

- `GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf` and `.md`: results,
  per-trial statistics and charts. The extended latency study appears within
  TC-14. Scheduler, burst, API capacity and HPA follow-up results appear within
  TC-18, TC-19, TC-23 and TC-24 respectively. Use PDF bookmarks to navigate.
- `GROUP02_INSTRUCTIONS.pdf` and `.md`: deployment and testing guide. The
  extended TC-14 procedure is in Section 9. Follow-up findings appear alongside
  their procedures in Sections 9.2-9.5; evidence scope is in Section 9.9.
  The documents have no Appendix A or B.

[Detailed findings](../../docs/FOLLOWUP_EVALUATION_RESULTS.md),
[article material and figures](../validation/followup-20261119/report/), and the
[evidence index](../../docs/VALIDATION_EVIDENCE.md) provide supporting data.
Highest observed capacity passes at API1/2/4 were 200/250/250 requests/s, with
3/3, 1/3 and 1/3 passing trials. All nine bursts and four full HPA cycles passed.

## Submission selection

Submit one copy of the results report and one copy of the instructions guide listed above.
The results report already includes the TC-14 extended results, both charts, methodology
and reproduction steps within TC-14, together with the other test cases and follow-up
studies. A separate TC-14 PDF is not needed for submission.

The redundant standalone TC-14 supplement and `_Revised.pdf` copies have been removed.
The instructions guide is kept under the regular filename above; the removed revised
copy had the same body content and only omitted "Examiner edition" from its cover subtitle.
The [TC-14 Markdown report](../../docs/TC14_EXTENDED_RESULTS.md) links the raw data and charts.

## Editing and rebuilding

Both PDFs render from their editable Markdown files in this directory.
Measured figures remain linked to their original evidence exports.
With reportlab and pypdf available, run:

```powershell
python experiments/refresh_followup_documents.py
```

The script rebuilds the integrated reports without adding appendices or cover
notices. Keep the follow-up reports, audits and figures and the
`output/tc14-extended-20261119/` cohort export available.
If Windows locks an existing PDF, the builder saves an `_Revised.pdf` copy in
this directory. Use that copy until the original is closed and rebuilt.
Render and inspect PDF changes. The historical `build_all25_report.py` also
recreates a combined report and is not the current follow-up refresh command.
Deleted combined/handbook artifacts were not recreated.

## Version and archive boundaries

[Appendix A verification](../../docs/FOLLOWUP_DOCUMENTATION_UPDATE.md)
records page checks and hashes from that edition. The earlier
[submission verification](../../docs/FINAL_SUBMISSION_VERIFICATION.md) and
[examiner-guide verification](../../docs/EXAMINER_GUIDE_VERIFICATION.md) remain
dated historical snapshots; their page counts and package hashes predate this refresh.

The final follow-up test ZIP and all earlier evidence/reviewer archives remain
sealed and unchanged. Supply current PDFs alongside the evidence ZIP for the
latest documentation. The extended TC-14 export is available in
[`output/tc14-extended-20261119/`](../tc14-extended-20261119/).
