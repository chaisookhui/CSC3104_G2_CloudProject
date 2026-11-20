"""Durable unit ledger and cooperative pause control (no lab work in this CLI).

Pause exits with 75. COMPLETE describes evidence completion, not a passing result.
Only the process owning a unit can commit it. Interrupted attempts are immutable.
"""
import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / '.local/test-results'
PAUSED = 75
_session = None
_cleanup = threading.local()
_sleep = time.sleep


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, default=str)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def source_identity():
    # Excludes generated reports, docs and unrelated packaging changes.
    paths = []
    for folder in ('src', 'frontend', 'infra'):
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file()
                     and p.suffix in ('.py', '.js', '.cjs', '.html', '.css', '.json', '.yaml', '.sql', '.txt')
                     and not any(s in p.parts for s in ('node_modules', '__pycache__', '.venv')))
    paths.extend(ROOT/p for p in ('demo.py', 'compose.core.yaml', 'requirements.txt') if (ROOT/p).exists())
    harness = ('control', 'run', 'study', 'runtime', 'loadgen', 'workloads', 'operations',
               'observability', 'resilience', 'fairness', 'gateway_check', 'followup', 'followup_capacity')
    paths.extend(ROOT/'experiments'/(name+'.py') for name in harness)
    return {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(set(paths)) if p.exists()}


class Pause(BaseException):
    def __init__(self, mode):
        self.mode = mode
        super().__init__('Requested ' + mode + ' pause; evidence retained')


@contextmanager
def cleanup():
    previous = getattr(_cleanup, 'active', False)
    _cleanup.active = True
    try:
        yield
    finally:
        _cleanup.active = previous


def immediate():
    if _session and not getattr(_cleanup, 'active', False):
        _session.check(immediate_only=True)


def active():
    return _session is not None


def boundary():
    if _session:
        _session.check()


def session():
    return _session


def plan(keys):
    if _session:
        for key in keys:
            _session.data['units'].setdefault(key,dict(state='PENDING',attempts=[]))
        _session.save()


def before_mutation():
    immediate()
    if _session:
        _session.verify()


def uncancellable(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with cleanup():
            return function(*args, **kwargs)
    return wrapped


def command(original, arguments, *, capture=False, source=None, check=True):
    if not _session:
        return original(arguments, capture=capture, source=source, check=check)
    immediate()
    with subprocess.Popen([str(arg) for arg in arguments], cwd=ROOT, text=True,
            stdin=subprocess.PIPE if source is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None) as process:
        try:
            first = True
            while True:
                try:
                    stdout, _ = process.communicate(input=source if first else None, timeout=.1)
                    break
                except subprocess.TimeoutExpired:
                    first = False
                    immediate()
        except BaseException:
            process.terminate()
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            raise
        if check and process.returncode:
            raise RuntimeError('Command failed: '+' '.join(map(str, arguments)))
        return (stdout or '').strip() if capture else process.returncode


def sleep(seconds):
    if not _session:
        _sleep(seconds)
        return
    deadline = time.monotonic() + seconds
    while True:
        immediate()
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            return
        _sleep(min(.1, remaining))


async def async_sleep(seconds):
    if not _session:
        await asyncio.sleep(max(0,seconds))
        return
    deadline = time.monotonic() + seconds
    while True:
        immediate()
        remaining = deadline-time.monotonic()
        if remaining <= 0:
            await asyncio.sleep(0)
            return
        await asyncio.sleep(min(.1, remaining))


def alive(pid):
    if os.name == 'nt':
        # os.kill(pid, 0) is NOT a safe Windows liveness probe.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # access denied is conservative
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def live_identity():
    """Read-only; no build, deploy, reset, image load or archive creation."""
    from runtime import k, local
    deployments = read_json_text(k('get', 'deployments', '-o', 'json', capture=True))
    pods = read_json_text(k('get', 'pods', '-o', 'json', capture=True))
    config = read_json_text(k('get', 'configmap', 'core-config', '-o', 'json', capture=True))['data']
    templates = {}
    for item in deployments['items']:
        spec = item['spec']['template']['spec']
        templates[item['metadata']['name']] = spec
    images = {}
    for pod in pods['items']:
        for container in pod.get('status', {}).get('containerStatuses', []):
            if not container.get('imageID'):
                raise RuntimeError('Cannot verify an unresolved pod image')
            images.setdefault(container['image'], set()).add(container['imageID'])
    if not templates or not images:
        raise RuntimeError('No lab deployments/images to verify; preserve evidence and restore the existing lab first')
    host_images = read_json_text(local.run(['docker', 'image', 'inspect', *local.IMAGES], capture=True))
    maps=read_json_text(k('get','configmaps','-o','json',capture=True))['items']
    stateful=read_json_text(k('get','statefulsets','-o','json',capture=True))['items']
    hpas=read_json_text(k('get','hpa','-o','json',capture=True))['items']
    secrets=read_json_text(k('get','secrets','-o','json',capture=True))['items']
    return dict(templates=templates, config=config, images={k: sorted(v) for k, v in images.items()},
                host_images={tag:i['Id'] for tag,i in zip(local.IMAGES,host_images)},
                configmaps={m['metadata']['name']:dict(data=m.get('data',{}),binaryData=m.get('binaryData',{})) for m in maps},
                statefulsets={s['metadata']['name']:s['spec']['template']['spec'] for s in stateful},
                hpa={h['metadata']['name']:h['spec'] for h in hpas},
                secrets_sha256={s['metadata']['name']:hashlib.sha256(json.dumps(s.get('data',{}),sort_keys=True).encode()).hexdigest() for s in secrets})


def read_json_text(value):
    return json.loads(value)


class Unit:
    def __init__(self, session, key, directory, legacy=None):
        self.session, self.key, self.directory = session, key, Path(directory)
        self.result, self.skip = None, False
        self.legacy = legacy

    def complete(self, result):
        self.result = result
        if not self.session:
            return
        # A request before the commit interrupts only this unit, even if its
        # workload summary was already written. Resume will use a fresh attempt.
        immediate()
        record = self.session.data['units'][self.key]
        record.update(state='COMPLETE', result=result, finished_at=now(),
                      evidence=self.session.evidence(self.directory))
        record['attempts'][-1].update(state='COMPLETE', finished_at=now())
        self.session.save()


class Session:
    def __init__(self, directory, configuration, resume=False, deployed=True, identity=None, live=None):
        self.directory = Path(directory)
        self.control = self.directory/'.control'
        self.path = self.control/'ledger.json'
        self.request_path = Path(os.environ.get('CSC3104_CONTROL', str(self.control/'request.json')))
        self.ack = os.environ.get('CSC3104_CONTROL_ACK')
        self.deployed = deployed
        self.live = live or live_identity
        self.lock = None
        self.cache_at = 0
        self.cached = None
        self.resuming = resume
        identity = identity if identity is not None else source_identity()
        if self.path.exists():
            if not resume:
                raise RuntimeError('Ledger exists; use the same command with --resume')
            self.data = read(self.path)
            if self.data['configuration'] != configuration:
                raise RuntimeError('Resume configuration/trace differs; no lab changes made')
            if self.data['source'] != identity:
                raise RuntimeError('Resume source differs; no lab changes made')
            for record in self.data['units'].values():
                if record['state'] == 'COMPLETE':
                    self.verify_evidence(record)
                elif record['state'] == 'RUNNING':
                    record['state'] = 'INTERRUPTED'
                    record['attempts'][-1].update(state='INTERRUPTED', reason='Previous process exited without a commit')
        else:
            self.data = dict(version=1, configuration=configuration, source=identity, units={}, state='READY', created_at=now())
        if self.request_path == self.control/'request.json':
            self.ack = read(self.request_path)['id'] if resume and self.request_path.exists() else None
        self.verified = False

    def save(self):
        atomic_json(self.path, self.data)
        atomic_json(self.control/'checkpoint.json', dict(state=self.data['state'], updated_at=now(),
            ledger=str(self.path), active=self.data.get('active'),
            active_child=self.data.get('active_child'),children=self.data.get('children',{}),
            complete=[k for k,v in self.data['units'].items() if v['state']=='COMPLETE'],
            unfinished=[k for k,v in self.data['units'].items() if v['state']!='COMPLETE'],
            configuration=self.data['configuration']))

    def evidence(self, directory):
        return {str(p.resolve()): sha(p) for p in sorted(Path(directory).rglob('*'))
                if p.is_file() and '.control' not in p.parts and not p.name.endswith('.tmp')}

    def verify_evidence(self, record):
        for path, expected in record['evidence'].items():
            if not Path(path).is_file() or sha(path) != expected:
                raise RuntimeError('Completed evidence changed or missing: '+path)

    def check(self, immediate_only=False):
        if not immediate_only or time.monotonic()-self.cache_at > .05:
            self.cached = read(self.request_path) if self.request_path.exists() else None
            self.cache_at = time.monotonic()
        request = self.cached
        if request and request['id'] != self.ack and (not immediate_only or request['mode']=='immediate'):
            raise Pause(request['mode'])

    def verify(self):
        if not self.verified and self.deployed:
            current = self.live()
            if 'live' in self.data and self.data['live'] != current:
                raise RuntimeError('Lab image/configuration/resources changed since checkpoint; no reset or rebuild performed')
            migration=ROOT/'output/validation/followup-20261119/continuation-ledger.json'
            if 'live' not in self.data and self.resuming and migration.exists():
                index=read(migration)
                if self.directory.name in index.get('legacy_resume_cohorts',[]):
                    anchor=index['consistency_anchor']
                    path=ROOT/anchor['path']
                    if sha(path)!=anchor['sha256']:
                        raise RuntimeError('Legacy pause identity anchor changed')
                    snapshot=read(path)
                    old_sources={k:v for k,v in snapshot['source_files_sha256'].items() if not k.startswith('experiments/')}
                    old_images={c['imageID'] for pod in snapshot['pods'] for c in pod['containers']}
                    new_images={value for values in current['images'].values() for value in values}
                    resources={d['name']:d['resources'] for d in snapshot['replicas']}
                    current_resources={name:[c.get('resources') for c in spec['containers']] for name,spec in current['templates'].items()}
                    if (snapshot['config']!=current['config'] or old_images!=new_images or resources!=current_resources
                            or any(self.data['source'].get(k)!=v for k,v in old_sources.items())):
                        raise RuntimeError('Legacy paused lab source/images/configuration/resources changed; no reset performed')
                    self.data['legacy_pause_anchor']=anchor
            self.data['live'] = current
            self.data.pop('verification_error',None)
            self.verified = True
            self.save()

    def adopt(self, key, directory, result):
        """One-time import of pre-ledger completed evidence; never imports partials."""
        directories = [Path(p) for p in result['legacy_directories']] if isinstance(result,dict) and 'legacy_directories' in result else [Path(directory)]
        if isinstance(result,dict) and 'legacy_directories' in result:
            result=result['result']
        snapshots = [p for directory in directories for p in directory.rglob('before.json')]
        if not snapshots:
            raise RuntimeError('Legacy evidence lacks a source/image capture: '+str(directory))
        for path in snapshots:
            snapshot = read(path)
            old = snapshot.get('source_files_sha256', {})
            application = {k:v for k,v in old.items() if not k.startswith('experiments/')}
            if not application or any(self.data['source'].get(k) != v for k,v in application.items()):
                raise RuntimeError('Legacy application/configuration source mismatch: '+str(path))
        self.verify()
        live_ids = {i for values in self.data['live']['images'].values() for i in values}
        old_ids = {c['imageID'] for p in read(snapshots[-1]).get('pods', []) for c in p['containers']}
        if not old_ids or not old_ids.issubset(live_ids):
            raise RuntimeError('Legacy deployed images differ from the current lab')
        evidence = {k:v for p in directories for k,v in self.evidence(p).items()}
        self.data['units'][key] = dict(state='COMPLETE', result=result, evidence=evidence,
            directory=str(directory), attempts=[], adopted=True, finished_at=now(),
            tooling_upgrade='Application/configuration/images verified; pre-ledger measurement harness retained in raw captures')
        self.save()

    @contextmanager
    def unit(self, key, directory, legacy=None):
        self.check()
        record = self.data['units'].get(key)
        if (not record or record['state']=='PENDING' and not record['attempts']) and legacy is not None and self.resuming:
            self.adopt(key, directory, legacy)
            record = self.data['units'][key]
        unit = Unit(self, key, directory)
        if record and record['state']=='COMPLETE':
            unit.skip, unit.result = True, record['result']
            unit.directory = Path(record['directory'])
            yield unit
            return
        self.verify()  # before reset, deployment, or any offered request
        attempts = record['attempts'] if record else []
        target = Path(directory)
        if target.exists() and any(p.name != '.control' for p in target.iterdir()):
            number = max(2,len(attempts)+1)
            while True:
                target = Path(str(directory)+f'-attempt-{number}')
                if not target.exists():
                    break
                number += 1
        target.mkdir(parents=True, exist_ok=True)
        unit.directory = target
        attempts.append(dict(directory=str(target), state='RUNNING', started_at=now()))
        record = dict(state='RUNNING', directory=str(target), attempts=attempts)
        self.data['units'][key] = record
        self.data.update(state='RUNNING', active=key)
        self.save()
        try:
            yield unit
            if record['state'] != 'COMPLETE':
                raise RuntimeError('Unit returned without committing its result: '+key)
        except BaseException as error:
            if record['state'] != 'COMPLETE':
                record.update(state='INTERRUPTED', finished_at=now(), error=type(error).__name__,
                              message=str(error), evidence=self.evidence(target))
                attempts[-1].update(state='INTERRUPTED', finished_at=now())
                atomic_json(target/'interrupted.json', dict(at=now(), unit=key, error=type(error).__name__, message=str(error)))
            raise
        finally:
            # Capture static deployment identity after intentional per-unit
            # changes/cleanup. Never mutate the lab to make it match.
            with cleanup():
                if self.deployed:
                    try:
                        self.data['live'] = self.live()
                    except Exception as error:
                        self.data['verification_error'] = str(error)
            self.data['active'] = None
            self.save()
        self.check()  # safe pause only AFTER the complete unit is durable

    @contextmanager
    def activate(self):
        global _session
        if _session:
            raise RuntimeError('Nested runner session')
        lock = RESULTS/'.runner.lock'
        lock.parent.mkdir(parents=True, exist_ok=True)
        if self.deployed:
            try:
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                owner = read(lock)
                if alive(owner['pid']):
                    raise RuntimeError('Another deployed runner is active: '+str(owner))
                lock.unlink()
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(descriptor, 'w') as stream:
                json.dump(dict(pid=os.getpid(), run=str(self.directory)), stream)
            self.lock = lock
        previous_env = {key: os.environ.get(key) for key in ('CSC3104_CONTROL', 'CSC3104_CONTROL_ACK')}
        os.environ['CSC3104_CONTROL'] = str(self.request_path)
        os.environ['CSC3104_CONTROL_ACK'] = self.ack or ''
        _session = self
        try:
            self.save()
            self.check()
            yield self
        except Pause as error:
            self.data.update(state='PAUSED', pause_mode=error.mode)
            self.save()
            raise
        except BaseException:
            self.data['state']='STOPPED'
            self.save()
            raise
        finally:
            _session = None
            for key,value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            if self.lock:
                self.lock.unlink(missing_ok=True)


@contextmanager
def unit(key, directory, legacy=None):
    if _session:
        with _session.unit(key, directory, legacy) as value:
            yield value
    else:
        yield Unit(None, key, directory)


def evidence_state(run, path):
    """Readers must not turn an interrupted attempt's early summary into PASS."""
    ledger=Path(run)/'.control/ledger.json'
    if not ledger.exists():
        return None
    target=Path(path).resolve()
    matches=[]
    for record in read(ledger)['units'].values():
        for attempt in record['attempts']:
            directory=Path(attempt['directory']).resolve()
            if target.is_relative_to(directory):
                matches.append((len(directory.parts),attempt['state']))
    return max(matches)[1] if matches else None


def controlled_main(function=None, *, deployed=True, driver=False):
    def decorate(fn):
        @wraps(fn)
        def wrapped():
            argv = sys.argv[1:]
            if any(v in argv for v in ('--help','--plan-only','--finalize-recorded')) or (argv and argv[0] in ('trace','lab','capture','invariants','autoscale')):
                return fn()
            if '--run' not in argv and '--prefix' not in argv:
                if not argv:
                    return fn()
                sys.argv += ['--run', 'run-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')]
                argv=sys.argv[1:]
            flag = '--run' if '--run' in argv else '--prefix'
            name = argv[argv.index(flag)+1]
            from runtime import run_directory
            directory = ROOT/'output/validation'/name if driver else run_directory(name)
            config = [v for v in argv if v != '--resume']
            if '--trace' in argv:
                config += ['trace_sha256='+sha(argv[argv.index('--trace')+1])]
            if '--prior' in argv:
                prior=RESULTS/argv[argv.index('--prior')+1]/'partial-results.json'
                config += ['prior_sha256='+sha(prior)]
            # Read compact checkpoint before ledger; source/evidence verified by Session.
            checkpoint = directory/'.control/checkpoint.json'
            if checkpoint.exists():
                read(checkpoint)
            session = Session(directory, config, '--resume' in argv, deployed)
            session.data['request_path']=str(session.request_path)
            try:
                with session.activate():
                    if session.data.get('finished'):
                        return session.data['exit_code']
                    result = fn()
                    session.check()
                    session.data.update(state='COMPLETE', finished=True, exit_code=result)
                    session.save()
                    return result
            except Pause as error:
                print(str(error), flush=True)
                return PAUSED
        return wrapped
    return decorate(function) if function else decorate


def child_call(command, **kwargs):
    """Child inherits the root pause signal; never advance after a child pause."""
    if _session:
        _session.check()
        _session.data.update(state='RUNNING',active_child=command)
        _session.save()
    code = subprocess.call(command, **kwargs)
    if _session:
        _session.data['active_child']=None
        if '--run' in command:
            run=command[command.index('--run')+1]
            _session.data.setdefault('children',{})[run]=dict(exit_code=code,ledger=str(RESULTS/run/'.control/ledger.json'))
        _session.save()
    if code == PAUSED:
        if _session:
            _session.check()
        raise Pause('immediate' if _session and _session.cached and _session.cached['mode']=='immediate' else 'safe')
    if _session:
        _session.check()
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['pause', 'status'])
    parser.add_argument('--run', required=True)
    parser.add_argument('--mode', choices=['safe', 'immediate'], default='safe')
    parser.add_argument('--driver', action='store_true', help='Control followup.py by its --prefix')
    args = parser.parse_args()
    import re
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', args.run):
        parser.error('Invalid run ID')
    directory = (ROOT/'output/validation' if args.driver else RESULTS)/args.run
    control = directory/'.control'
    if not (control/'ledger.json').exists():
        parser.error('No controlled runner ledger exists for this run')
    if args.action=='pause':
        request_path=Path(read(control/'ledger.json').get('request_path',str(control/'request.json')))
        atomic_json(request_path, dict(id=uuid.uuid4().hex, mode=args.mode, requested_at=now()))
        print('Requested '+args.mode+' pause; wait for state PAUSED / runner exit 75 before closing the terminal.')
    else:
        print(json.dumps(read(control/'checkpoint.json'), indent=2))


if __name__=='__main__':
    main()
