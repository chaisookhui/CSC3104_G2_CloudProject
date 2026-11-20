"""Build one source-and-evidence submission ZIP without running application tests.

Uses reviewed evidence exports, never the private .local directory wholesale.
Run from the repository root: python experiments/build_submission.py
"""
import hashlib
import hmac
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile
from datetime import datetime, timezone

from build_instructions import build as build_instructions
from build_results_report import build as build_results

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/review-package'
PREFIX = 'CSC3104_G2_CloudProject/'
PDFS = ('GROUP02_INSTRUCTIONS.pdf',
        'GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def credentials():
    """Use the same configured-secret checks as the existing export tooling."""
    values = set()
    for path in (ROOT / '.local/k8s').glob('secrets-*.json'):
        config = json.loads(path.read_text())
        values.update(v.encode() for v in config.values() if isinstance(v, str) and len(v) >= 12)
        token = config.get('PAYMENT_API_TOKEN')
        if token:
            for purpose in (b'csc3104:admin-password', b'csc3104:operator'):
                values.add(hmac.new(token.encode(), purpose, hashlib.sha256).hexdigest().encode())
    env = ROOT / '.env.core'
    if env.exists():
        for line in env.read_text().splitlines():
            if '=' not in line or line.startswith('#'):
                continue
            key, value = line.split('=', 1)
            value = value.strip().strip('\"\'')
            if any(s in key.upper() for s in ('PASSWORD', 'TOKEN', 'SECRET')) and len(value) >= 12:
                values.add(value.encode())
    return values


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    scratch = ROOT / 'tmp/pdfs/submission'
    scratch.mkdir(parents=True, exist_ok=True)
    # Render fresh copies for the ZIP even when a viewer locks a public PDF.
    build_instructions(scratch / PDFS[0])
    build_results(scratch / PDFS[1])
    secrets = credentials()
    entries, origins, exported = {}, [], {}

    def safe(name, data):
        parts = PurePosixPath(name).parts
        require(not PurePosixPath(name).is_absolute() and '..' not in parts
                and '\\' not in name and ':' not in name, 'Unsafe archive path: ' + name)
        require(not any(p in parts for p in ('.git', '.aws', '.codex', '.agents',
                                             'examiner-browser-profiles')), 'Private path: ' + name)
        require(not any(v in data for v in secrets), 'Configured credential detected: ' + name)
        return data

    # Archive entries are references until written, avoiding an uncompressed in-memory bundle.
    archives = []
    try:
        checks = json.loads((OUT / 'package-verification.json').read_text())
        baseline = next(p for p in checks['packages'] if p['archive'] == 'GROUP02_Raw_Results_and_Graphs.zip')
        followup_dir = ROOT / 'output/validation/followup-20261119'
        followup = json.loads((followup_dir / 'export-verification.json').read_text())
        for path, expected in ((OUT / baseline['archive'], baseline['sha256']),
                               (followup_dir / followup['archive'], followup['sha256'])):
            require(sha(path.read_bytes()) == expected, 'Evidence archive checksum mismatch: ' + path.name)
            origins.append({'path': path.relative_to(ROOT).as_posix(), 'sha256': expected})
            archive = zipfile.ZipFile(path)
            archives.append(archive)
            for info in archive.infolist():
                name = info.filename.removeprefix(PREFIX)
                if info.is_dir() or not name.startswith(('.local/test-results/', 'output/validation/', 'review/graphs/')):
                    continue
                if PurePosixPath(name).suffix.lower() in ('.zip', '.pdf', '.pyc'):
                    continue
                require(name not in entries, 'Conflicting evidence path: ' + name)
                entries[name] = (archive, info.filename)

        # Public working-tree files; ignored diagnostics and private originals stay excluded.
        candidates = subprocess.check_output(
            ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT
        ).decode().split('\0')
        forbidden = {'.git', '.local', '.venv', 'venv', '__pycache__', 'node_modules', '.aws', '.codex', '.agents'}
        for name in sorted(set(candidates)):
            relative = PurePosixPath(name)
            path = ROOT / name
            if not name or any(p in forbidden for p in relative.parts) or not path.is_file():
                continue
            if name.startswith(('tmp/', 'output/validation/', 'output/review-package/')):
                continue
            if relative.name.startswith('CHECKPOINT') or relative.name == 'WORK_LOG.md':
                continue
            if relative.name.startswith('.env') and relative.name not in ('.env.example', '.env.sample', '.env.template'):
                continue
            if relative.suffix.lower() in ('.zip', '.pyc', '.db', '.sqlite3', '.key', '.pfx', '.p12'):
                continue
            if relative.suffix.lower() == '.pdf':
                continue  # Only the two freshly rendered submission PDFs below.
            require(ROOT in path.resolve().parents, 'Source path escapes workspace')
            entries[name] = path
        cohort = ROOT / 'output/tc14-extended-20261119'
        require(cohort.is_dir(), 'Missing TC14 export')
        for path in cohort.rglob('*'):
            if path.is_file() and path.suffix.lower() not in ('.zip', '.pdf', '.pyc'):
                require(ROOT in path.resolve().parents, 'TC14 path escapes workspace')
                entries[path.relative_to(ROOT).as_posix()] = path
        for name in PDFS:
            entries['output/pdf/' + name] = scratch / name

        def read(value):
            return value[0].read(value[1]) if isinstance(value, tuple) else value.read_bytes()

        audit_path = 'output/validation/all25/all25-audit.json'
        audit = json.loads(read(entries[audit_path]))
        require(audit['status'] == 'PASS' and len(audit['cases']) == 25, 'Incomplete case ledger')
        cases = {}
        for case, result in audit['cases'].items():
            folder = result['evidence'].rstrip('/')
            files = [n for n in entries if n.startswith(folder + '/')]
            require(bool(files), 'Missing case evidence: ' + case + ': ' + folder)
            cases[case] = {'path': folder, 'included_files': len(files)}
        required = [audit_path, 'output/validation/all25/final-acceptance-audit.json',
                    'output/validation/all25/checker-corrections.json',
                    'output/validation/tc-fixes/FINAL_REPORT.md', 'output/validation/tc-fixes/ROOT_CAUSES.md',
                    'output/validation/followup-20261119/raw-audit.json',
                    'output/validation/followup-20261119/report/RESULTS.md',
                    'output/tc14-extended-20261119/raw-observations.csv',
                    'output/tc14-extended-20261119/summary.json']
        require(all(n in entries for n in required), 'Missing required reports or raw exports')
        start = '''# Submission: start here

Extract GROUP02_Submission.zip once and open CSC3104_G2_CloudProject/.
All paths in the testing guide are relative to this folder. The submission
contains current source and exactly two PDFs under output/pdf/.

## Verify recorded results

1. Open output/validation/all25/all25-audit.json. Each case's evidence field
   selects its recorded folder under .local/test-results/. All 25 selected
   folders are included. Preserve preliminary failures when interpreting passes.
2. Historical performance reports: output/validation/tc-fixes/FINAL_REPORT.md
   and ROOT_CAUSES.md. These describe their original cohorts.
3. Follow-up: output/validation/followup-20261119/report/RESULTS.md and
   raw-audit.json, with raw followup-20261119-* folders in .local/test-results/.
4. Extended TC14: output/tc14-extended-20261119/ contains raw observations,
   summaries, charts and trial-level inventory, deployment and SQL evidence.

Example manual run IDs such as TC-01, TC19-exam and TC23-exam in the guide are
destinations created by new reruns. Use the audit ledger for recorded run IDs.
Recorded evidence can be inspected without Docker or changing a deployment.
New application tests require the prerequisites in the instructions guide.

SUBMISSION_MANIFEST.json hashes every payload file. SUBMISSION_VERIFICATION.json
lists the selected case folders, checked required files and input archive hashes.
These are packaging checks; no new application tests were run. Configured local
credentials, browser profiles and private runtime state are excluded.

The original sealed evidence ZIPs remain unchanged on the author's machine.
Their exported contents are included directly here; nested archives and older
duplicate PDF editions are unnecessary. Historical records may name those
original archives or removed PDF editions; use this current guide and manifest.
'''
        baseline_capture = json.loads(read(entries['.local/test-results/tc-fix-19-v9/surge-1/before.json']))
        application = {n: h for n, h in baseline_capture['source_files_sha256'].items()
                       if n.startswith(('src/', 'frontend/', 'infra/')) or n == 'demo.py'}
        require(bool(application) and all(n in entries and sha(read(entries[n])) == h
                                         for n, h in application.items()),
                'Application/configuration differs from the recorded validated build')
        provenance = {
            'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
            'working_tree_snapshot': True,
            'application_files_compared': len(application),
            'application_matches_validated_v9': True,
            'no_application_tests_rerun': True,
            'status': subprocess.check_output(['git', 'status', '--short'], cwd=ROOT).decode().splitlines(),
        }
        generated = {'START_HERE.md': start.encode(),
                     'SOURCE_PROVENANCE.json': json.dumps(provenance, indent=2).encode()}
        target = OUT / 'GROUP02_Submission.zip'
        pending = target.with_suffix('.pending.zip')
        with zipfile.ZipFile(pending, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
            for name, value in sorted(entries.items()):
                data = safe(name, read(value))
                zipped.writestr(PREFIX + name, data)
                exported[name] = {'sha256': sha(data), 'bytes': len(data)}
            for name, data in generated.items():
                zipped.writestr(PREFIX + name, data)
                exported[name] = {'sha256': sha(data), 'bytes': len(data)}
            verification = {'status': 'PASS', 'created_at': datetime.now(timezone.utc).isoformat(),
                            'scope': 'Packaging integrity and evidence availability; no new application tests',
                            'origin_archives': origins, 'cases': cases, 'required_files': required,
                            'pdfs': ['output/pdf/' + n for n in PDFS], 'payload_files': len(exported)}
            zipped.writestr(PREFIX + 'SUBMISSION_VERIFICATION.json', json.dumps(verification, indent=2))
            zipped.writestr(PREFIX + 'SUBMISSION_MANIFEST.json', json.dumps(exported, indent=2))
        with zipfile.ZipFile(pending) as zipped:
            require(len(zipped.namelist()) == len(set(zipped.namelist())), 'Duplicate ZIP entries')
            require(sorted(n.removeprefix(PREFIX) for n in zipped.namelist() if n.endswith('.pdf'))
                    == sorted('output/pdf/' + n for n in PDFS), 'Unexpected PDF copies')
            for name, expected in exported.items():
                require(sha(zipped.read(PREFIX + name)) == expected['sha256'], 'ZIP hash mismatch: ' + name)
        pending.replace(target)
        report = dict(verification, archive=target.name, sha256=sha(target.read_bytes()), bytes=target.stat().st_size)
        (OUT / 'submission-verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        print(json.dumps({k: report[k] for k in ('status', 'archive', 'bytes', 'payload_files', 'sha256')}, indent=2))
    finally:
        for archive in archives:
            archive.close()


if __name__ == '__main__':
    main()
