# Submission checklist

## What to submit

Submit the [repository URL](https://github.com/chaisookhui/CSC3104_G2_CloudProject).
Its README links to the [complete submission release](https://github.com/chaisookhui/CSC3104_G2_CloudProject/releases/latest).
Download the attached `GROUP02_Submission.zip`, extract it once and open
`CSC3104_G2_CloudProject/START_HERE.md`. GitHub's automatic source-code ZIP omits
ignored raw evidence. The current tested source is on `twy`.

## Documents and recorded evidence

- `output/pdf/GROUP02_INSTRUCTIONS.pdf`: deployment, test procedures and evidence navigation.
- `output/pdf/GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf`: all 25 baseline cases, extended TC-14 and follow-up findings.
- `output/validation/all25/all25-audit.json`: recorded case selection and retained failure history.
- `.local/test-results/`: reviewed raw evidence exported into the submission ZIP.
- `output/validation/tc-fixes/`: original workload reports and audits.
- `output/validation/followup-20261119/`: follow-up reports, tables and audits.
- `output/tc14-extended-20261119/`: extended latency observations and trial evidence.

The baseline audit passed 321 checks across 25 cases. The follow-up saved-data audit
passed 1,046 checks; its capacity outcomes remain mixed. Completion is not a PASS.
These are recorded local results and do not establish production reliability.

## Package verification

Run `python experiments/build_submission.py` with reportlab and pypdf installed.
The builder renders the two current PDFs, verifies its reviewed archive inputs,
checks all 25 selected case folders and required reports, compares 96 application/
configuration files with the recorded validated build, and verifies every payload
hash after writing the ZIP. No application workloads run during packaging.

`SUBMISSION_MANIFEST.json` records the actual payload hashes.
`SUBMISSION_VERIFICATION.json` records case paths, required files and provenance.
Raw timestamps, expiry deadlines and original run identifiers remain intact for
verification. Superseded planning notes, document-edit histories and the standalone
TC-14 supplement builder are omitted; the current reports contain their relevant results.
