"""Export the new examiner runs with hashes, excluding private browser profiles.

The original sealed v9 ZIP is referenced by checksum, not rewritten. Credentials
are redacted only in exported copies; private originals retain diagnostic value.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[1]
TEXT={'.txt','.log','.json','.jsonl','.csv','.md','.py','.cjs','.yaml','.sql','.patch'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--audit',type=Path,required=True);args=p.parse_args();args.audit=args.audit.resolve()
    audit=json.loads(args.audit.read_text());assert audit['status']=='PASS' and len(audit['cases'])==25
    out=args.audit.parent;files=set()
    for run in {a['run'] for a in audit['attempts']}:
        files.update(f for f in (ROOT/'.local/test-results'/run).rglob('*') if f.is_file())
    files.update(f for f in out.rglob('*') if f.is_file() and f.suffix not in ('.zip','.pyc') and f.name not in ('evidence-manifest.json','export-verification.json','evidence-zip.sha256'))
    for name in ('examiner_verify.py','examiner_browser.cjs','examiner_audit.py','build_all25_report.py','export_examiner_evidence.py','runtime.py','workloads.py','acceptance.py','SCALING_STUDIES.md','EXAMINER_VERIFICATION.md'):
        files.add(ROOT/'experiments'/name)
    for name in ('GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf','GROUP02_Test_Results_and_Distributed_Concepts_Report.md','GROUP02_INSTRUCTIONS.pdf','GROUP02_INSTRUCTIONS.md'):
        files.add(ROOT/'output/pdf'/name)
    values=set()
    for source in (ROOT/'.local/k8s').glob('secrets-*.json'):
        values.update(v.encode() for v in json.loads(source.read_text()).values() if isinstance(v,str) and len(v)>=12)
    env=ROOT/'.env.core'
    if env.exists():
        for line in env.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                key,value=line.split('=',1)
                if any(word in key.upper() for word in ('PASSWORD','TOKEN','SECRET')) and len(value.strip())>=12:values.add(value.strip().strip('\"\'').encode())
    def export(path):
        data=path.read_bytes()
        if path.suffix.lower() in TEXT:
            for value in sorted(values,key=len,reverse=True):data=data.replace(value,b'[REDACTED]')
            data=re.sub(rb'(postgres(?:ql)?://[^\s:/]+:)[^@\s]+(@)',rb'\1[REDACTED]\2',data)
        if any(v in data for v in values):raise RuntimeError('Configured secret remains in '+str(path.relative_to(ROOT)))
        return data
    entries=[]
    for path in sorted(files):
        assert path.is_file() and ROOT in path.resolve().parents
        assert '.local/examiner-browser-profiles/' not in path.as_posix()
        raw=path.read_bytes();data=export(path)
        entries.append(dict(path=path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(data).hexdigest(),original_sha256=hashlib.sha256(raw).hexdigest(),bytes=len(data),redacted=data!=raw))
    prior=ROOT/'output/validation/tc-fixes/evidence-zip.sha256'
    manifest=dict(files=entries,prior_performance_evidence=prior.read_text().strip(),prior_location='output/validation/tc-fixes/',scope='New final-version15-case raw evidence, all25 audit, report sources and current PDFs; full earlier v9 workloads remain in the separately sealed original evidence ZIP.')
    manifest_path=out/'evidence-manifest.json';manifest_path.write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    archive=out/'GROUP02_All25_Additional_Evidence.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in sorted(files):z.writestr(path.relative_to(ROOT).as_posix(),export(path))
        z.write(manifest_path,manifest_path.relative_to(ROOT).as_posix())
    errors=[];json_count=0
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:errors.append('ZIP CRC failure')
        for entry in entries:
            data=z.read(entry['path'])
            if hashlib.sha256(data).hexdigest()!=entry['sha256']:errors.append('Hash mismatch '+entry['path'])
            if any(v in data for v in values):errors.append('Configured secret '+entry['path'])
            if entry['path'].endswith('.json'):
                try:json.loads(data);json_count+=1
                except (ValueError,UnicodeError):errors.append('Unreadable JSON '+entry['path'])
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    (out/'evidence-zip.sha256').write_text(digest+'  '+archive.name+'\n')
    result=dict(status='FAIL' if errors else 'PASS',entries=len(entries)+1,bytes=archive.stat().st_size,sha256=digest,json_files=json_count,redacted_files=sum(e['redacted'] for e in entries),errors=errors)
    (out/'export-verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
    if errors:raise RuntimeError('Evidence export verification failed')


if __name__=='__main__':main()
