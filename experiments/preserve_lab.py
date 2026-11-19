"""Read-only export before a follow-up resets csc3104-lab; never exports Secrets."""
import argparse
import hashlib
import json
import zipfile

from observability import collect_logs, sample
from runtime import ROOT, LAB, api, capture, k, lab_connection, run_directory, utc, write_json


def preserve(run):
    directory = run_directory(run)
    if any(directory.iterdir()):
        raise ValueError('Choose a fresh preservation run ID')
    write_json(directory/'run.json', dict(namespace=LAB, at=utc(), purpose=__doc__))
    # Seal original measurements and submission documents, byte-for-byte.
    originals = [p for p in (ROOT/'.local/test-results').rglob('*')
                 if p.is_file() and directory not in p.parents]
    for folder in ('output/pdf', 'output/validation/all25', 'output/validation/tc-fixes'):
        originals.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix != '.zip')
    manifest = {}
    with zipfile.ZipFile(directory/'prior-evidence.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(originals)):
            name = path.relative_to(ROOT).as_posix()
            raw = path.read_bytes()
            manifest[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
            archive.writestr(name, raw)
    write_json(directory/'prior-files.json', manifest)
    with lab_connection() as base:
        write_json(directory/'lab-before.json', capture(base, 'follow-up-preservation', 'before-reset'))
        write_json(directory/'inventory.json', {s:api(base, 'seats/seats/'+s) for s in 'ABCD'})
    write_json(directory/'resources.json', sample())
    # Dumps contain lab records, not database users/passwords or kubeconfig.
    for database in ('seats', 'payment', 'allocation', 'dispatcher'):
        dump = k('exec', 'postgres-0', '--', 'pg_dump', '-U', 'postgres', '-d', database,
                 '--no-owner', '--no-privileges', capture=True)
        (directory/(database+'.sql')).write_text(dump, encoding='utf-8')
    # Redis DUMP is arbitrary binary, including bytes Windows' text decoder
    # cannot represent. Encode in the pod and capture ASCII JSON only.
    source="""import os,json,base64,redis
client=redis.Redis.from_url(os.environ['REDIS_URL'])
keys=sorted(client.keys('*'))
pipe=client.pipeline(transaction=True)
for key in keys:pipe.dump(key);pipe.pttl(key)
values=pipe.execute()
print(json.dumps([dict(key_base64=base64.b64encode(key).decode('ascii'),
    dump_base64=base64.b64encode(values[2*i]).decode('ascii') if values[2*i] is not None else None,
    pttl=values[2*i+1]) for i,key in enumerate(keys)]))
"""
    records=json.loads(k('exec','deployment/waiting-room','--','python','-c',source,capture=True))
    write_json(directory/'redis-records.json',dict(format='redis-dump-base64-v1',at=utc(),records=records))
    collect_logs(directory)
    # Verify original files and ZIP contents before authorizing a reset.
    with zipfile.ZipFile(directory/'prior-evidence.zip') as archive:
        for name, record in manifest.items():
            if hashlib.sha256((ROOT/name).read_bytes()).hexdigest() != record['sha256']:
                raise RuntimeError('Original evidence changed: '+name)
            if hashlib.sha256(archive.read(name)).hexdigest() != record['sha256']:
                raise RuntimeError('Archive verification failed: '+name)
    write_json(directory/'summary.json', dict(status='PASS', at=utc(), files_sealed=len(manifest),
        archive_sha256=hashlib.sha256((directory/'prior-evidence.zip').read_bytes()).hexdigest(),
        interpretation='Read-only lab snapshot and verified byte-preserving original-evidence archive; no new workload result.'))
    print('Preserved', len(manifest), 'original files and existing lab state in', directory, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True)
    preserve(parser.parse_args().run)
