"""Export a new, verified follow-up bundle; never rewrite original archives."""
import argparse
import hashlib
import hmac
import json
import re
import zipfile

from runtime import ROOT, RESULTS, utc, write_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix',required=True)
    parser.add_argument('--output-name',default='GROUP02_Followup_Evidence.zip')
    args=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,65}',args.prefix):parser.error('Invalid prefix')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+\.zip',args.output_name):parser.error('Use a ZIP filename')
    out=ROOT/'output/validation'/args.prefix
    archive=out/args.output_name
    if archive.exists():raise ValueError('Choose a new output filename; exported evidence is preserved')
    files=set()
    for run in RESULTS.glob(args.prefix+'-*'):
        if 'preserve' in run.name and not re.search(r'preserve-pause[0-9]*$',run.name):
            continue  # The private original archive stays private and unchanged.
        if run.is_dir():files.update(p for p in run.rglob('*') if p.is_file() and p.suffix!='.pyc' and '__pycache__' not in p.parts)
        elif run.is_file():files.add(run)
    files.update(p for p in out.rglob('*') if p.is_file() and p.suffix not in ('.zip','.pyc') and p.name not in ('export-manifest.json','export-verification.json'))
    for cohort in out.parent.glob(args.prefix+'-*'):
        if cohort.is_dir():
            files.update(p for p in cohort.rglob('*') if p.is_file() and p.suffix not in ('.zip','.pyc'))
    files.update(p for p in (ROOT/'experiments').glob('*') if p.is_file() and p.suffix in ('.py','.sql','.md','.txt'))
    files.add(ROOT/'tests/test_followup_studies.py')
    files.add(ROOT/'tests/test_hpa_finalization.py')
    for name in ('tests/test_pause_resume.py','tests/test_async_loadgen.py','tests/test_load_completeness.py',
                 'tests/test_followup_reporting.py','CHECKPOINT_FOLLOWUP_EVALUATION_HISTORY_20261119.md',
                 'docs/FOLLOWUP_EVALUATION_RESULTS.md','docs/VALIDATION_EVIDENCE.md'):
        if (ROOT/name).exists():files.add(ROOT/name)
    for name in ('test_pause_resume.py','test_async_loadgen.py','test_load_completeness.py'):
        files.add(ROOT/'tests'/name)
    for name in ('AGENTS.md','CHECKPOINT_FOLLOWUP_EVALUATION.md'):
        if (ROOT/name).exists():files.add(ROOT/name)
    secrets=set()
    for source in (ROOT/'.local/k8s').glob('secrets-*.json'):
        config=json.loads(source.read_text())
        secrets.update(v.encode() for v in config.values() if isinstance(v,str) and len(v)>=12)
        token=config.get('PAYMENT_API_TOKEN')
        if token:
            for purpose in (b'csc3104:admin-password',b'csc3104:operator'):
                secrets.add(hmac.new(token.encode(),purpose,hashlib.sha256).hexdigest().encode())
    env=ROOT/'.env.core'
    if env.exists():
        for line in env.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                key,value=line.split('=',1)
                if any(t in key.upper() for t in ('PASSWORD','TOKEN','SECRET')) and len(value)>=12:
                    secrets.add(value.strip().strip('\"\'').encode())
    def exported(path):
        data=path.read_bytes()
        if path.suffix.lower() in ('.json','.jsonl','.csv','.log','.txt','.md','.py','.sql','.yaml'):
            for value in sorted(secrets,key=len,reverse=True):data=data.replace(value,b'[REDACTED]')
            data=re.sub(rb'(postgres(?:ql)?://[^\s:/]+:)[^@\s]+(@)',rb'\1[REDACTED]\2',data)
            data=re.sub(rb'(?i)(Bearer\s+)[A-Za-z0-9._~-]+',rb'\1[REDACTED]',data)
        if any(s in data for s in secrets):raise RuntimeError('Credential remains in '+path.name)
        return data
    entries=[]
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as zipped:
        for path in sorted(files):
            relative=path.resolve().relative_to(ROOT.resolve()).as_posix()
            if any(s in path.parts for s in ('examiner-browser-profiles','.git','.aws')):raise ValueError('Private path')
            data=exported(path)
            zipped.writestr(relative,data)
            entries.append(dict(path=relative,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data),
                original_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),redacted=data!=path.read_bytes()))
        manifest=dict(at=utc(),files=entries,scope='Fresh follow-up attempts, analysis and runner sources; original sealed evidence is preserved separately.')
        zipped.writestr('FOLLOWUP_MANIFEST.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(archive) as zipped:
        if zipped.testzip() is not None:raise ValueError('ZIP CRC failure')
        for entry in entries:
            data=zipped.read(entry['path'])
            if hashlib.sha256(data).hexdigest()!=entry['sha256']:raise ValueError('ZIP hash mismatch')
            if entry['path'].endswith('.json'):json.loads(data)
    write_json(out/'export-manifest.json',manifest)
    write_json(out/'export-verification.json',dict(status='PASS',at=utc(),archive=archive.name,
        files=len(entries),bytes=archive.stat().st_size,sha256=hashlib.sha256(archive.read_bytes()).hexdigest()))
    print(archive)


if __name__=='__main__':main()
