"""Lab-only experiment plumbing. No cluster credentials are put in the frontend."""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'infra/k8s'))
import local

LAB = 'csc3104-lab'
RESULTS = ROOT / '.local/test-results'


def utc():
    return datetime.now(timezone.utc).isoformat()


def run_directory(name=None):
    name = name or datetime.now(timezone.utc).strftime('run-%Y%m%d-%H%M%S-%f')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', name):
        raise ValueError('Use a short run ID with letters, numbers, dots, hyphens or underscores')
    path = RESULTS / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, default=str), encoding='utf-8')


def k(*args, **kwargs):
    # The caller cannot select a different namespace.
    return local.kubectl(*args, namespace=LAB, **kwargs)


def sql(database, statement):
    if database not in ('seats', 'payment', 'allocation', 'dispatcher'):
        raise ValueError('Unexpected experiment database')
    return k('exec', '-i', 'postgres-0', '--', 'psql', '-U', 'postgres', '-d', database,
             '-v', 'ON_ERROR_STOP=1', '-tA', capture=True, source=statement)


def invariants():
    checks = json.loads(sql('seats', (ROOT / 'experiments/invariants.sql').read_text(encoding='utf-8')))
    payment = json.loads(sql('payment', """SELECT json_build_object(
      'duplicate_pending', (SELECT count(*) FROM (SELECT hold_id FROM wy_payments
       WHERE attempt_status='pending' GROUP BY hold_id HAVING count(*)>1) p),
      'duplicate_success', (SELECT count(*) FROM (SELECT hold_id FROM wy_payments
       WHERE attempt_status='succeeded' GROUP BY hold_id HAVING count(*)>1) p));"""))
    counts = json.loads(sql('seats', """SELECT json_build_object(
      'holds', (SELECT count(*) FROM holds), 'seats', (SELECT count(*) FROM seats),
      'confirmed', (SELECT count(*) FROM seats WHERE state='CONFIRMED'),
      'held', (SELECT count(*) FROM seats WHERE state='HELD'));"""))
    violations = sum(int(row['violations']) for row in checks) + sum(payment.values())
    return dict(seat_checks=checks, payment_checks=payment, counts=counts,
                violations=violations, status='FAIL' if violations else
                'PASS' if counts['holds'] else 'INCONCLUSIVE_EMPTY', captured_at=utc())


def request(base, path, body=None, timeout=15):
    payload = None if body is None else json.dumps(body).encode()
    started = time.perf_counter()
    sent = utc()
    headers={'Content-Type':'application/json'}
    credentials=local.LOCAL/('secrets-'+LAB+'.json')
    if credentials.exists():
        token=json.loads(credentials.read_text())['PAYMENT_API_TOKEN']
        headers['Authorization']='Bearer '+hmac.new(token.encode(),b'csc3104:operator',hashlib.sha256).hexdigest()
    req = Request(base.rstrip('/') + '/api/' + path, data=payload, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as response:
            status, raw = response.status, response.read().decode()
            instance=response.headers.get('X-Service-Instance')
    except HTTPError as error:
        status, raw = error.code, error.read().decode()
        instance=error.headers.get('X-Service-Instance')
    except (URLError, TimeoutError, OSError) as error:
        return dict(status=0, data=None, error=type(error).__name__, sent_at=sent,
                    elapsed_ms=(time.perf_counter()-started)*1000)
    try:
        data = json.loads(raw)
    except ValueError:
        data = raw
    return dict(status=status, data=data, sent_at=sent, instance=instance, elapsed_ms=(time.perf_counter()-started)*1000)


def api(base, path, body=None):
    response = request(base, path, body)
    if not 200 <= response['status'] < 300:
        raise RuntimeError(f'{path}: HTTP {response["status"]}; {response.get("data") or response.get("error")}')
    return response['data']


def guard_lab(base):
    parsed = urlparse(base)
    if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost'):
        raise ValueError('Experiments require an HTTP loopback lab address')
    context = api(base, 'demo/context')
    if context.get('namespace') != LAB or context.get('is_lab') is not True:
        raise RuntimeError('Refusing to run: the frontend is not csc3104-lab')
    return context


@contextmanager
def lab_connection():
    with socket.socket() as temporary:
        temporary.bind(('127.0.0.1', 0))
        port = temporary.getsockname()[1]
    command = [str(local.kubectl_binary()), '--kubeconfig', str(local.KUBECONFIG),
               '--context', local.CONTEXT, '--namespace', LAB, 'port-forward',
               '--address', '127.0.0.1', 'service/frontend', f'{port}:8080']
    log_path = ROOT / '.local/k8s/experiment-port-forward.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('w') as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log,
                                   stdin=subprocess.DEVNULL)
        try:
            base = f'http://127.0.0.1:{port}'
            deadline = time.monotonic() + 30
            while True:
                if process.poll() is not None:
                    raise RuntimeError('Lab port-forward stopped. See ' + str(log_path))
                try:
                    guard_lab(base)
                    break
                except (RuntimeError, ValueError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Lab frontend unavailable or not the lab. See ' + str(log_path))
                    time.sleep(.3)
            yield base
        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def setup_lab(reset=False, policy='demand-cycle', hold_ttl=300, batch_size=10):
    if policy not in ('demand-cycle', 'fcfs') or not 1 <= batch_size <= 100 or not 20 <= hold_ttl <= 900:
        raise ValueError('Invalid lab policy, batch size (1-100), or hold TTL (20-900 seconds)')
    if reset:
        local.kubectl('delete', 'namespace', LAB, '--ignore-not-found', '--wait=true', '--timeout=180s',namespace=None)
        (local.LOCAL / ('secrets-' + LAB + '.json')).unlink(missing_ok=True)
    elif policy != 'demand-cycle':
        raise ValueError('Changing allocation policy requires an explicit --reset-lab')
    else:
        previous=k('get','configmap','core-config','--ignore-not-found','-o','json',capture=True)
        if previous and json.loads(previous).get('data',{}).get('ALLOCATION_POLICY','demand-cycle') != policy:
            raise ValueError('Changing an existing lab policy requires --reset-lab')
    local.deploy(LAB, hold_ttl=hold_ttl, batch_size=batch_size, policy=policy)


def capture(base, case='manual', phase='snapshot'):
    guard_lab(base)
    result = dict(case=case, phase=phase, namespace=LAB, captured_at=utc(), observations={})
    for name, path in [('queue', 'waiting-room/queue'), ('waiting', 'waiting-room/status'),
                       ('dispatcher', 'dispatcher/status'), ('allocator', 'allocation/ready'),
                       ('payment_health', 'payment/health'), ('payment_metrics', 'payment/metrics')]:
        result['observations'][name] = request(base, path)
    for name, command in [('pods', ('get', 'pods', '-o', 'json')),
                           ('pvc', ('get', 'pvc', '-o', 'json')),
                           ('config', ('get', 'configmap', 'core-config', '-o', 'json')),
                           ('replicas', ('get', 'deployments', '-o', 'json'))]:
        try:
            data = json.loads(k(*command, capture=True))
            if name == 'pods':
                data = [dict(name=p['metadata']['name'], uid=p['metadata']['uid'],
                             phase=p['status'].get('phase'), containers=p['status'].get('containerStatuses', []))
                        for p in data['items']]
            elif name == 'replicas':
                data = [dict(name=d['metadata']['name'], desired=d['spec'].get('replicas'),
                             ready=d['status'].get('readyReplicas', 0),
                             resources=[c.get('resources') for c in d['spec']['template']['spec']['containers']])
                        for d in data['items']]
            elif name == 'pvc':
                data = [dict(name=p['metadata']['name'], uid=p['metadata']['uid'],
                             phase=p['status'].get('phase')) for p in data['items']]
            else:
                data = data.get('data', {})
            result[name] = data
        except (RuntimeError, ValueError) as error:
            result[name] = {'unavailable': str(error)}
    try:
        result['invariants'] = invariants()
        result['allocation_backlog'] = json.loads(sql('allocation',
            "SELECT COALESCE(json_object_agg(state,n),'{}') FROM (SELECT state,count(*) n FROM allocation_jobs GROUP BY state) s;"))
        result['payment_monitor'] = json.loads(k('exec', 'deployment/payment-api', '--',
                                                 'python', 'service.py', 'monitor', capture=True))
    except (RuntimeError, ValueError) as error:
        result['database_observation_error'] = str(error)
    try:
        result['resource_metrics']={'available':True,'observed_at':utc(),
                                    'pod_cpu_memory':k('top','pods','--no-headers',capture=True)}
    except RuntimeError:
        result['resource_metrics']={'available':False,'observed_at':utc(),
                                    'reason':'Resource metrics unavailable; no CPU/memory/HPA result can be inferred'}
    try:
        result['hpa']=json.loads(k('get','hpa','-o','json',capture=True))
        result['database_connections']=json.loads(sql('seats',
            "SELECT json_agg(row_to_json(s)) FROM (SELECT state,count(*) FROM pg_stat_activity GROUP BY state) s;"))
    except (RuntimeError,ValueError) as error:
        result['operations_observation_error']=str(error)
    for key, command in [('commit', ['git', 'rev-parse', 'HEAD']),
                          ('changed_files', ['git', 'status', '--short'])]:
        result[key] = local.run(command, capture=True, check=False)
    diff = local.run(['git', 'diff'], capture=True, check=False)
    result['tracked_diff_sha256'] = hashlib.sha256(diff.encode()).hexdigest()
    source_files=[]
    for folder in ('experiments','frontend','infra','src'):
        source_files.extend(path for path in (ROOT/folder).rglob('*') if path.is_file() and
            path.suffix in ('.py','.js','.cjs','.html','.css','.json','.yaml','.sql','.txt') and
            not any(part in ('.venv','node_modules','__pycache__') for part in path.parts))
    source_files.append(ROOT/'demo.py')
    result['source_files_sha256']={str(path.relative_to(ROOT)).replace('\\','/'):
        hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(source_files)}
    result['working_source_sha256']=hashlib.sha256(json.dumps(result['source_files_sha256'],sort_keys=True).encode()).hexdigest()
    try:
        info=json.loads(local.run(['docker','info','--format','{{json .}}'],capture=True))
        result['runtime']={key:info.get(key) for key in ('ServerVersion','OSType','Architecture','NCPU','MemTotal','CgroupVersion','Driver','KernelVersion')}
        result['runtime'].update(kind=local.KIND_VERSION,kubectl=local.KUBECTL_VERSION)
    except (RuntimeError,ValueError):
        result['runtime']={'unavailable':True}
    return result
