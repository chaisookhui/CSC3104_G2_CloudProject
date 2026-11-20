# Submission documents

There are two submission PDFs:

- `GROUP02_INSTRUCTIONS.pdf`: deployment, testing and evidence navigation.
- `GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf`: the 25-case baseline,
  extended TC-14 results, and scheduler, burst, API-capacity and HPA follow-up studies.

Both reports integrate extensions within their relevant test cases. The separate
TC-14 supplement and duplicate PDF editions are unnecessary.

The instructions explain **how to test**; the results report explains **what was
observed**. Raw evidence supplies the underlying request records, logs, screenshots
and database checks that verify those findings. Most raw evidence is provided in
the release ZIP rather than tracked directly in the branch. The
[evidence index](../../docs/VALIDATION_EVIDENCE.md) maps its extracted folders.

Submit the [repository URL](https://github.com/chaisookhui/CSC3104_G2_CloudProject).
The [submission release](https://github.com/chaisookhui/CSC3104_G2_CloudProject/releases/latest)
provides `GROUP02_Submission.zip`, containing these two PDFs, current source and
exported evidence at the paths used in the guide. Start with its `START_HERE.md`.

## Rebuild

Edit the Markdown sources here. With reportlab and pypdf installed, run:

```powershell
python experiments/refresh_followup_documents.py
python experiments/build_submission.py
```

Close PDF viewers before replacing the public copies. The submission builder
always renders fresh PDFs for its ZIP. Keep the recorded evidence exports intact;
their run identifiers and timestamps support independent verification.

See the [submission checklist](../../docs/FINAL_SUBMISSION_VERIFICATION.md) and
[evidence index](../../docs/VALIDATION_EVIDENCE.md).
