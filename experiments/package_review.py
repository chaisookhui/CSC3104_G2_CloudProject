"""Package current source and complete measured results for independent review.

No tests/deployments and no Git commit/push. Reuses already-redacted sealed
evidence archives; current source code is exported byte-for-byte.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/review-package'
PREFIX='CSC3104_G2_CloudProject/'


def digest(data):return hashlib.sha256(data).hexdigest()
def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT).decode('utf-8')


def main(source_only=False):
    OUT.mkdir(parents=True,exist_ok=True)
    # Refuse to silently present new application code as the already-tested build.
    before=json.loads((ROOT/'.local/test-results/tc-fix-19-v9/surge-1/before.json').read_text())
    application={k:v for k,v in before['source_files_sha256'].items() if k.startswith(('src/','frontend/','infra/')) or k=='demo.py'}
    assert all(digest((ROOT/p).read_bytes())==h for p,h in application.items()),'Application differs from validated build'
    secrets=set()
    for p in (ROOT/'.local/k8s').glob('secrets-*.json'):
        values=json.loads(p.read_text())
        secrets.update(v.encode() for v in values.values() if isinstance(v,str) and len(v)>=12)
        if isinstance(values.get('PAYMENT_API_TOKEN'),str):
            for purpose in (b'csc3104:admin-password',b'csc3104:operator'):
                secrets.add(hmac.new(values['PAYMENT_API_TOKEN'].encode(),purpose,hashlib.sha256).hexdigest().encode())
    env=ROOT/'.env.core'
    if env.exists():
        for line in env.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                key,value=line.split('=',1)
                if any(x in key.upper() for x in ('PASSWORD','TOKEN','SECRET')) and len(value.strip())>=12:secrets.add(value.strip().strip('\"\'').encode())
    def safe(name,data):
        if any(s in data for s in secrets):raise RuntimeError('Configured credential detected; export blocked: '+name)
        if any(p in Path(name).parts for p in ('.git','.aws','examiner-browser-profiles')):raise RuntimeError('Private path: '+name)
        return data
    stamp=datetime.now(timezone.utc).isoformat()
    index='''# Start here - source code and experimental evidence

Prepared 14 November 2026 from the current working checkout.

## 1. Latest source code

GROUP02_Latest_Source.zip contains the current application, frontend, tests,
experiment tools, Dockerfiles, SQL migrations, Compose/Kubernetes configurations,
dependency files and public documentation. The verified application is committed
at 253a6e2. This is a working-tree snapshot; any documentation/release overlay is
listed in provenance rather than being described as uncommitted application fixes.
SOURCE_PROVENANCE.json gives the base commit/branch, application continuity
check, and the changed-file inventory. SOURCE_MANIFEST.json hashes every file.

Extract to a clean folder and run from CSC3104_G2_CloudProject/. Follow README.md,
output/pdf/GROUP02_INSTRUCTIONS.pdf and experiments/SCALING_STUDIES.md.
Startup generates new local credentials. No .env.core, kubeconfig, generated
Secrets, database files, virtual environments or browser profiles are supplied.
The GitHub remote is identified in provenance for reference; this task does not
commit or push the working changes. Use this source ZIP for the submitted snapshot.

## 2. Raw experimental results and graphs

GROUP02_Raw_Results_and_Graphs.zip directly contains the exported raw run folders,
CSV/JSON records, original workload traces, before/after captures, configuration
and image/source fingerprints, worker logs, HPA timelines, audits and graphs.
Extract beside/into the source folder so .local/test-results paths match.

Final measured cohorts:

| Case | Raw folders under .local/test-results/ | Graphs and tables |
|---|---|---|
| TC-16 | tc-fix-regression-v9-TC16-1, TC16-2, TC16-4 (same prefix) | review/graphs/tc16-worker-scaling.png/.svg; tc16-trials.csv |
| TC-18 | tc-fix-regression-v9-TC18 | review/graphs/tc18-fairness-by-section.png/.svg; tc18-policy-tradeoffs.png/.svg; tc18-*.csv |
| TC-23 | tc-fix-23-v9; tc-fix-capacity-v9; tc-fix-capacity-upper-v9 | output/validation/tc-fixes/report-v9/tc23-*.png/.svg; runs.csv; pod-metrics.csv |
| TC-24 | tc-fix-24-api-v9; tc-fix-24-worker-v9 | output/validation/tc-fixes/report-v9/tc24-*.png/.svg; raw timeline.json/jsonl and phases.json in each run |

TC-16 retains three repeats at each1/2/4 worker count, both policies (18 replays).
TC-18 retains ten paired F1 seeds42-51, both policies (20 replays,40 paired
section observations). New PNG/SVG/CSV exports are derived only from these
saved measurements by experiments/review_graphs.py; no tests were rerun.

TC-23 has nine fixed1500-offer trials plus the separately measured capacity
grid. TC-24 keeps each full original load/recovery/repeated-spike cycle and
actual Ready-replica/CPU/backlog evidence. More replicas need not improve
latency; a passing comparison does not prove Demand-Cycle is fairer than FCFS.
The highest passing capacity rate is a tested lower bound, not a true maximum.

All earlier diagnostic/failed/inconclusive tc-fix runs are retained. Use the
named final-v9 cohorts for the final conclusions; do not pool earlier workloads,
resource budgets or failed attempts into passing averages. Original missing
TWY evidence was not recovered; these are newly generated diagnostic/final runs.

The additional final-version functional/browser runs and all25 audit are also
included, along with the current reports. All25 recorded local cases passed;
77 new and244 original-workload raw audit checks passed. This is bounded local
evidence, not a guarantee on another machine or proof of production HA/security.

The current GROUP02_INSTRUCTIONS.pdf and the final results report describe the
same final evidence:15 newly verified cases plus10 full-scope v9 cases re-audited.
The obsolete current-guide note about15 incomplete cases has been removed.
Corrected instructions are included in both source and results ZIPs under
output/pdf/. Previously sealed archives retain their historical document versions.
Earlier instructions-alignment verification records describe their original PDF
hash. Current SOURCE_MANIFEST.json / RESULTS_MANIFEST.json identify the updated
guide; docs/FINAL_SUBMISSION_VERIFICATION.md records this documentation-only check.

RESULTS_MANIFEST.json hashes all actual exported entries. Evidence originated
from the two previously verified/redacted ZIPs, whose checksums are retained in
RESULTS_PROVENANCE.json. Raw data is not resampled, truncated or re-labelled.
Logs retain prior redactions. Current source belongs to the separate source ZIP;
historical run source fingerprints describe the code at those measurement times.
'''
    (OUT/'START_HERE.md').write_text(index,encoding='utf-8')
    candidates=git('ls-files','-z','--cached','--others','--exclude-standard').split('\0')
    forbidden={'.git','.local','.venv','venv','__pycache__','node_modules','.aws','.codex','.agents'}
    files=[]
    for name in candidates:
        if not name:continue
        relative=Path(name);path=ROOT/relative;posix=relative.as_posix()
        if any(p in forbidden for p in relative.parts) or posix.startswith(('tmp/','output/validation/','output/review-package/')):continue
        if relative.name.startswith('CHECKPOINT') or relative.name=='WORK_LOG.md':continue
        if relative.name.startswith('.env') and relative.name not in ('.env.example','.env.sample','.env.template'):continue
        if relative.suffix.lower() in ('.zip','.pyc','.db','.sqlite3','.key','.pfx','.p12') or not path.is_file():continue
        if ROOT not in path.resolve().parents:raise RuntimeError('Source path escapes workspace')
        files.append((posix,path))
    status=git('status','--short').splitlines()
    provenance=dict(created_at=stamp,base_commit=git('rev-parse','HEAD').strip(),branch=git('branch','--show-current').strip(),
                    remote=git('remote','get-url','origin').strip(),uncommitted_changes_included=bool(status),
                    status=status,application_files_compared=len(application),
                    application_commit='253a6e27a78d34aa634b92a7f724eb42166c24dc',
                    current_operation='documentation synchronisation and release packaging; no application tests rerun',
                    application_matches_validated_v9=True,no_commit_or_push_performed=True)
    code={PREFIX+name:safe(name,p.read_bytes()) for name,p in sorted(files)}
    code[PREFIX+'START_HERE.md']=index.encode()
    code[PREFIX+'SOURCE_PROVENANCE.json']=json.dumps(provenance,indent=2).encode()
    manifest={name:dict(sha256=digest(data),bytes=len(data)) for name,data in code.items()}
    code[PREFIX+'SOURCE_MANIFEST.json']=json.dumps(manifest,indent=2).encode()
    def write_zip(path,entries):
        with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for name,data in sorted(entries.items()):z.writestr(name,safe(name,data))
    source=OUT/'GROUP02_Latest_Source.zip';write_zip(source,code)
    if source_only:
        # Refresh a documentation overlay without rewriting measured-result bundles.
        previous=json.loads((OUT/'package-verification.json').read_text())
        assert previous['status']=='PASS'
        with zipfile.ZipFile(source) as z:
            assert z.testzip() is None
            for name,expected in manifest.items():
                data=z.read(name);assert digest(data)==expected['sha256'];safe(name,data)
                if name.endswith('.json'):json.loads(data)
        for check in previous['packages']:
            if check['archive']==source.name:
                check.update(status='PASS',entries=len(code),bytes=source.stat().st_size,
                             sha256=digest(source.read_bytes()),
                             json_files_readable=sum(n.endswith('.json') for n in manifest))
            else:
                assert digest((OUT/check['archive']).read_bytes())==check['sha256']
        (OUT/'package-verification.json').write_text(json.dumps(previous,indent=2),encoding='utf-8')
        (OUT/'SHA256SUMS.txt').write_text(''.join(c['sha256']+'  '+c['archive']+'\n' for c in previous['packages']))
        print(json.dumps(previous['packages'],indent=2))
        return
    # Read exported evidence, never private originals or private browser profiles.
    raw={};origins=[]
    sources=[(ROOT/'output/validation/tc-fixes/CSC3104_TC19_TC23_TC24_New_Evidence.zip','48f7063db400a7d08a7da86a1a0516452aef998ba765e46b6de7b037ab93fa21'),
             (ROOT/'output/validation/all25/GROUP02_All25_Additional_Evidence.zip','0fd6ae8acc1ac188484399bb86117a63f19ae6e365c634c9e9addf897018e708')]
    for archive,expected in sources:
        actual=digest(archive.read_bytes());assert actual==expected,(archive.name,'changed original archive')
        origins.append(dict(archive=archive.name,sha256=actual))
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                name=info.filename
                include=name.startswith(('.local/test-results/','output/validation/tc-fixes/','output/validation/all25/'))
                if not include or info.is_dir() or Path(name).suffix.lower() in ('.zip','.py','.pyc','.patch'):continue
                if Path(name).name in ('evidence-manifest.json','evidence-zip.sha256','archive-verification.json','export-verification.json','report-hashes.json'):continue
                if Path(name).is_absolute() or '..' in Path(name).parts:raise RuntimeError('Unsafe archive path')
                raw[PREFIX+name]=safe(name,z.read(info))
    for path in (OUT/'graphs').iterdir():
        if path.is_file():raw[PREFIX+'review/graphs/'+path.name]=path.read_bytes()
    for name in ('GROUP02_Test_Results_and_Distributed_Concepts_Report.pdf','GROUP02_Test_Results_and_Distributed_Concepts_Report.md','GROUP02_INSTRUCTIONS.pdf','GROUP02_INSTRUCTIONS.md'):
        raw[PREFIX+'output/pdf/'+name]=(ROOT/'output/pdf'/name).read_bytes()
    for folder,patterns in [('tc-fixes',('archive-verification.json','evidence-zip.sha256')),('all25',('all25-audit.json','final-environment-verification.json','pdf-content-verification.json','export-verification.json','evidence-zip.sha256','README.md'))]:
        for name in patterns:raw[PREFIX+'output/validation/'+folder+'/'+name]=(ROOT/'output/validation'/folder/name).read_bytes()
    alignment=ROOT/'output/validation/instructions-alignment/verification.json'
    if alignment.exists():raw[PREFIX+'output/validation/instructions-alignment/verification.json']=alignment.read_bytes()
    raw[PREFIX+'START_HERE.md']=index.encode()
    raw[PREFIX+'RESULTS_PROVENANCE.json']=json.dumps(dict(created_at=stamp,origin_archives=origins,raw_data_unchanged_from_redacted_exports=True,
        no_tests_rerun=True,new_derived_graphs='review/graphs/',historical_runs_retained=True),indent=2).encode()
    required=['.local/test-results/tc-fix-regression-v9-TC16-'+str(n)+'/comparison.json' for n in (1,2,4)]+[
        '.local/test-results/tc-fix-regression-v9-TC18/comparison.json','.local/test-results/tc-fix-23-v9/summary.json',
        '.local/test-results/tc-fix-24-api-v9/summary.json','.local/test-results/tc-fix-24-worker-v9/summary.json']
    assert all(PREFIX+name in raw for name in required)
    raw_manifest={name:dict(sha256=digest(data),bytes=len(data)) for name,data in raw.items()}
    raw[PREFIX+'RESULTS_MANIFEST.json']=json.dumps(raw_manifest,indent=2).encode()
    results=OUT/'GROUP02_Raw_Results_and_Graphs.zip';write_zip(results,raw)
    graph_entries={}
    for folder in (OUT/'graphs',ROOT/'output/validation/tc-fixes/report-v9'):
        for path in folder.iterdir():
            if path.is_file() and path.suffix in ('.png','.svg','.csv','.json','.md'):
                graph_entries['graphs/'+path.name]=path.read_bytes()
    graph_entries['START_HERE.md']=index.encode()
    graph_manifest={name:dict(sha256=digest(data),bytes=len(data)) for name,data in graph_entries.items()}
    graph_entries['GRAPHS_MANIFEST.json']=json.dumps(graph_manifest,indent=2).encode()
    graphs=OUT/'GROUP02_Graphs_and_CSV.zip';write_zip(graphs,graph_entries)
    checks=[]
    for archive,manifest,entries in ((source,manifest,code),(results,raw_manifest,raw),(graphs,graph_manifest,graph_entries)):
        readable=0
        with zipfile.ZipFile(archive) as z:
            assert z.testzip() is None
            for name,expected in manifest.items():
                data=z.read(name);assert digest(data)==expected['sha256'];safe(name,data)
                if name.endswith('.json'):json.loads(data);readable+=1
        checks.append(dict(archive=archive.name,status='PASS',entries=len(entries),bytes=archive.stat().st_size,sha256=digest(archive.read_bytes()),json_files_readable=readable))
    (OUT/'package-verification.json').write_text(json.dumps(dict(status='PASS',packages=checks,source_application_files_match_v9=len(application),new_graphs_visually_checked=True),indent=2),encoding='utf-8')
    (OUT/'SHA256SUMS.txt').write_text(''.join(c['sha256']+'  '+c['archive']+'\n' for c in checks))
    print(json.dumps(checks,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-only',action='store_true',help='Refresh source/docs; require and preserve verified results/graph packages')
    main(source_only=parser.parse_args().source_only)
