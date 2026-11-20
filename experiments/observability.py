"""Shared preconditions and timestamped, incremental lab evidence."""
from contextlib import contextmanager
import json
import os
import sys
import threading
import control
import time

from runtime import api, guard_lab, k, sql, utc, write_json


def host_resources():
    result=dict(logical_cpus=os.cpu_count())
    if sys.platform=='win32':
        import ctypes
        class Memory(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong)]+[
                (name,ctypes.c_ulonglong) for name in ('total_physical','free_physical','commit_limit',
                    'available_commit','total_virtual','free_virtual','extended')]
        memory=Memory();memory.length=ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            result.update(physical_total_bytes=memory.total_physical,free_physical_bytes=memory.free_physical,
                          commit_limit_bytes=memory.commit_limit,available_commit_bytes=memory.available_commit)
    return result


def ready_replicas(name, count):
    d = json.loads(k('get', 'deployment', name, '-o', 'json', capture=True))
    s = d.get('status', {})
    return (d['spec']['replicas'] == count and s.get('observedGeneration', 0) >= d['metadata']['generation']
            and all(s.get(key, 0) == count for key in ('replicas', 'updatedReplicas', 'readyReplicas', 'availableReplicas')))


def preflight(base, metrics=True):
    guard_lab(base)
    host=host_resources()
    if host.get('available_commit_bytes',1024**3)<256*1024**2:
        raise RuntimeError('Host has less than 256 MiB available commit memory; preserve the workload and free resources before retrying')
    deployments = json.loads(k('get', 'deployments', '-o', 'json', capture=True))['items']
    for deployment in deployments:
        name = deployment['metadata']['name']
        if not ready_replicas(name, deployment['spec']['replicas']):
            raise RuntimeError('Deployment not fully ready: ' + name)
    if k('exec', 'redis-0', '--', 'redis-cli', 'ping', capture=True).strip() != 'PONG':
        raise RuntimeError('Redis ping failed')
    for database in ('seats', 'payment', 'allocation', 'dispatcher'):
        if sql(database, 'SELECT 1;').strip() != '1':
            raise RuntimeError('PostgreSQL connection failed: ' + database)
    for path in ('waiting-room/ready', 'allocation/ready', 'seats/health', 'payment/health', 'dispatcher/ready'):
        api(base, path)
    if metrics:
        k('get', '--raw', '/apis/metrics.k8s.io/v1beta1/namespaces/csc3104-lab/pods', capture=True)
    return dict(at=utc(), deployments=len(deployments), redis='PONG', databases='reachable', metrics_required=metrics,host=host)


def sample(queue_meta=None):
    value = dict(at=utc(), monotonic=time.monotonic(), host=host_resources(),errors={})
    for key, command in (
        ('deployments', ('get', 'deployments', '-o', 'json')),
        ('hpa', ('get', 'hpa', '-o', 'json')),
        ('pods', ('get', 'pods', '-o', 'json')),
        ('metrics', ('get', '--raw', '/apis/metrics.k8s.io/v1beta1/namespaces/csc3104-lab/pods'))):
        try:
            value[key] = json.loads(k(*command, capture=True))
        except (RuntimeError, ValueError) as error:
            value['errors'][key] = str(error)
    try:
        value['backlog'] = json.loads(sql('allocation', "SELECT COALESCE(json_object_agg(state,n),'{}') FROM (SELECT state,count(*) n FROM allocation_jobs GROUP BY state) s;"))
    except (RuntimeError, ValueError) as error:
        value['errors']['backlog'] = str(error)
    try:
        # Exclude query text/credentials; retain shared-store wait/connection
        # evidence for capacity and worker-demand diagnosis.
        value['database_activity']=json.loads(sql('seats', "SELECT COALESCE(json_agg(row_to_json(s)),'[]') FROM (SELECT datname,state,wait_event_type,wait_event,count(*) AS connections FROM pg_stat_activity GROUP BY datname,state,wait_event_type,wait_event) s;"))
        raw=k('exec','redis-0','--','redis-cli','INFO',capture=True)
        value['redis_info']={line.split(':',1)[0]:line.split(':',1)[1] for line in raw.splitlines() if line and not line.startswith('#') and ':' in line}
        if queue_meta:
            phase,count=json.loads(k('exec','redis-0','--','redis-cli','--json','HMGET',queue_meta,'phase','queued_count',capture=True))
            phase=phase or 'PRE_SALE'
            value['waiting_queue']=dict(phase=phase,queued_count=0 if phase=='PRE_SALE' else int(count) if count is not None else None)
    except (RuntimeError,ValueError) as error:
        value['errors']['shared_stores']=str(error)
    return value


@contextmanager
def monitor(directory, interval=5):
    stop = threading.Event()
    samples = []
    config=json.loads(k('get','configmap','core-config','-o','json',capture=True))['data']
    queue_meta=config['QUEUE_KEY']+':v2:meta'
    def collect():
        with (directory/'timeline.jsonl').open('a', encoding='utf-8') as output:
            while not stop.is_set():
                try:
                    value = sample(queue_meta)
                except control.Pause:
                    break
                samples.append(value)
                output.write(json.dumps(value)+'\n')
                output.flush()
                stop.wait(interval)
    thread = threading.Thread(target=collect)
    thread.start()
    try:
        yield samples
    finally:
        stop.set()
        thread.join()
        write_json(directory/'timeline.json', samples)
        collect_logs(directory)


@control.uncancellable
def collect_logs(directory):
    errors = {}
    for key, command in [('events', ('get', 'events', '-o', 'json'))] + [
        (name, ('logs', '-l', 'app='+name, '--all-containers=true', '--prefix=true', '--timestamps=true', '--tail=300', '--max-log-requests=8'))
        for name in ('waiting-room', 'allocation-worker', 'dispatcher-worker', 'frontend', 'redis', 'postgres',
                     'seat-api', 'seat-worker', 'payment-api', 'payment-worker', 'dispatcher-api',
                     'allocation-api', 'waiting-recovery')]:
        try:
            (directory/(key+'.log')).write_text(k(*command, capture=True), encoding='utf-8')
        except RuntimeError as error:
            errors[key] = str(error)
    try:
        pods=json.loads(k('get','pods','-o','json',capture=True))
        write_json(directory/'pods-final.json',pods)
        for pod in pods['items']:
            for container in pod.get('status',{}).get('containerStatuses',[]):
                if container.get('restartCount',0):
                    name=pod['metadata']['name'];cname=container['name']
                    try:
                        (directory/(name+'-'+cname+'-previous.log')).write_text(k('logs',name,'-c',cname,
                            '--previous','--timestamps=true',capture=True),encoding='utf-8')
                    except RuntimeError as error:
                        errors[name+'-previous']=str(error)
    except (RuntimeError,ValueError) as error:
        errors['pods-final']=str(error)
    write_json(directory/'log-errors.json', errors)
