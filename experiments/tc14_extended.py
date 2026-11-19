"""Measure sequential seat-store holds in five fresh, disposable Kind namespaces."""

import argparse
from contextlib import contextmanager
from functools import partial
from http.client import HTTPConnection, HTTPException
import json
import os
import platform
import subprocess
import time
from uuid import uuid4

from control import sha
from runtime import ROOT, invariants, local, run_directory, utc, write_json
from workloads import write_rows

TRIALS = 5
WARMUP = 10
MEASURED = 100
SECTION = 'C'
ROWS = 20
TTL = 300
TIMEOUT = 15
ENDPOINT = '/seats/hold'

FIXTURE_SQL = f"""
BEGIN;
UPDATE sections SET row_count = {ROWS} WHERE section = 'C' AND row_count = 1;
INSERT INTO seats (seat_id, section, row, position_in_row)
SELECT format('C-%s-%s', r, p), 'C', r, p
FROM generate_series(2, {ROWS}) AS r CROSS JOIN generate_series(1, 10) AS p;
COMMIT;
"""


def sql(kube, database, statement):
    return kube('exec', '-i', 'postgres-0', '--', 'psql', '-U', 'postgres', '-d', database,
                '-v', 'ON_ERROR_STOP=1', '-tA', capture=True, source=statement)


def http(port, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {'Connection': 'close'}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    sent_at = utc()
    started = time.perf_counter_ns()
    connection = HTTPConnection('127.0.0.1', port, timeout=TIMEOUT)
    status, raw, error = None, None, None
    try:
        connection.request('GET' if body is None else 'POST', path, body, headers)
        response = connection.getresponse()
        status = response.status
        raw = response.read()
    except (OSError, HTTPException) as exc:
        error = f'{type(exc).__name__}: {exc}'
        raw = getattr(exc, 'partial', None)
    finally:
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        connection.close()
    response_body = raw.decode('utf-8', errors='replace') if raw is not None else None
    return dict(sent_at=sent_at, latency_ms=elapsed_ms, status=status,
                response_body=response_body, transport_error=error)


def response_data(response):
    try:
        return json.loads(response['response_body'] or '')
    except ValueError:
        return None


def classify(response, request_id):
    body = response_data(response)
    if response['transport_error']:
        return 'TRANSPORT_ERROR', None, None
    if response['status'] != 200:
        return 'HTTP_ERROR', None, None
    if isinstance(body, dict):
        if body.get('success') is False:
            return 'UNAVAILABLE', None, None
        seats = body.get('seats')
        if (body.get('success') is True and body.get('request_id') == request_id
                and body.get('hold_status') == 'ACTIVE' and body.get('hold_id')
                and isinstance(seats, list) and len(seats) == 1 and isinstance(seats[0], dict)):
            seat = seats[0]
            if (seat.get('section') == SECTION and seat.get('state') == 'HELD'
                    and seat.get('held_by_request_id') == request_id
                    and seat.get('hold_id') == body['hold_id'] and seat.get('seat_id')):
                return 'RESERVED', body['hold_id'], seat['seat_id']
    return 'INVALID_RESPONSE', None, None


@contextmanager
def seat_connection(namespace, directory):
    command = [str(local.kubectl_binary()), '--kubeconfig', str(local.KUBECONFIG),
               '--context', local.CONTEXT, '-n', namespace, 'port-forward',
               '--address', '127.0.0.1', 'service/seat-api', ':5003']
    log_path = directory / 'port-forward.log'
    with log_path.open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline and process.poll() is None:
                for line in log_path.read_text(encoding='utf-8').splitlines():
                    if line.startswith('Forwarding from 127.0.0.1:'):
                        port = int(line.split(':')[1].split()[0])
                        health = http(port, '/health')
                        if health['status'] == 200 and response_data(health) == {
                            'service': 'seat-store', 'status': 'ok', 'storage': 'postgresql',
                        }:
                            yield port
                            return
                time.sleep(0.2)
            raise RuntimeError('Seat-store port-forward failed readiness. See port-forward.log.')
        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def inventory(port):
    response = http(port, f'/seats/{SECTION}')
    data = response_data(response)
    if response['status'] != 200 or not isinstance(data, list):
        raise RuntimeError(f'Could not read seat inventory: {response}')
    return data


def deployment(kube):
    config = json.loads(kube('get', 'configmap', 'core-config', '-o', 'json', capture=True))['data']
    config.pop('EXPERIMENT_NAMESPACE')
    controllers = json.loads(kube('get', 'deployment,statefulset', '-o', 'json', capture=True))['items']
    replicas = {item['metadata']['name']: dict(desired=item['spec']['replicas'],
        ready=item['status'].get('readyReplicas', 0)) for item in controllers}
    pods = json.loads(kube('get', 'pods', '-o', 'json', capture=True))['items']
    running = {}
    identities = {}
    for pod in pods:
        if pod['metadata'].get('labels', {}).get('job'):
            continue
        component = pod['metadata']['labels']['app']
        if component in running:
            raise RuntimeError(f'Expected one Pod for {component}')
        statuses = {item['name']: item for item in pod['status']['containerStatuses']}
        running[component] = dict(node=pod['spec']['nodeName'], containers={
            container['name']: dict(image=container['image'],
                image_id=statuses[container['name']]['imageID'],
                command=container.get('command'), args=container.get('args'),
                resources=container.get('resources', {}), ready=statuses[container['name']]['ready'])
            for container in pod['spec']['containers']})
        identities[component] = dict(uid=pod['metadata']['uid'], restart_counts={
            name: status['restartCount'] for name, status in statuses.items()})
    if (set(running) != set(replicas) or any(counts != {'desired': 1, 'ready': 1}
            for counts in replicas.values()) or any(not c['ready'] or not c['image_id']
            for pod in running.values() for c in pod['containers'].values())):
        raise RuntimeError('TC-14 requires one Ready Pod per component, with recorded image IDs')
    if json.loads(kube('get', 'hpa', '-o', 'json', capture=True))['items']:
        raise RuntimeError('TC-14 requires fixed replicas')
    return dict(configuration=dict(config=config, replicas=replicas, pods=running), pod_identities=identities)


def host_metadata():
    info = json.loads(local.run(['docker', 'info', '--format', '{{json .}}'], capture=True))
    nodes = json.loads(local.kubectl('get', 'nodes', '-o', 'json', namespace=None, capture=True))['items']
    paths = [*sorted(local.MANIFESTS.glob('*.yaml')), ROOT / 'infra/docker/init-core-db.sh',
             ROOT / 'infra/k8s/local.py', ROOT / 'experiments/runtime.py',
             ROOT / 'experiments/invariants.sql', ROOT / 'experiments/tc14_extended.py']
    return dict(host=dict(platform=platform.platform(), processor=platform.processor(),
                          logical_cpus=os.cpu_count(), python=platform.python_version()),
                docker={key: info[key] for key in ('ServerVersion', 'OSType', 'Architecture', 'NCPU',
                                                   'MemTotal', 'CgroupVersion', 'Driver', 'KernelVersion')},
                kind=local.KIND_VERSION, kubectl=local.KUBECTL_VERSION, context=local.CONTEXT,
                nodes=[dict(name=n['metadata']['name'], info=n['status']['nodeInfo'],
                            capacity=n['status']['capacity'], allocatable=n['status']['allocatable']) for n in nodes],
                git_commit=local.run(['git', 'rev-parse', 'HEAD'], capture=True),
                source_sha256={path.relative_to(ROOT).as_posix(): sha(path) for path in paths})


def trial(namespace, directory, run_id, number, observations, result):
    kube = partial(local.kubectl, namespace=namespace)
    local.deploy(namespace, hold_ttl=TTL, batch_size=10)
    query = partial(sql, kube)
    query('seats', FIXTURE_SQL)
    result['deployment_before'] = deployment(kube)
    result['sql_before'] = invariants(query)
    with seat_connection(namespace, directory) as port:
        initial = inventory(port)
        write_json(directory / 'inventory-before.json', initial)
        expected_seats = [f'{SECTION}-{row}-{pos}' for row in range(1, ROWS + 1) for pos in range(1, 11)]
        if ([s['seat_id'] for s in initial] != expected_seats or
                any(s['state'] != 'AVAILABLE' or s['hold_id'] is not None for s in initial) or
                result['sql_before']['counts']['holds'] or result['sql_before']['violations']):
            raise RuntimeError('The starting inventory is not the expected clean 200-seat Section C fixture')
        with (directory / 'observations.jsonl').open('x', encoding='utf-8') as journal:
            for phase, count in [('warmup', WARMUP), ('measured', MEASURED)]:
                for index in range(1, count + 1):
                    request_id = f'{run_id}-t{number:02d}-{phase}-{index:03d}'
                    payload = dict(request_id=request_id, section=SECTION, party_size=1)
                    response = http(port, ENDPOINT, payload)
                    outcome, hold_id, seat_id = classify(response, request_id)
                    row = dict(trial=number, phase=phase, index=index, **payload, **response,
                               outcome=outcome, hold_id=hold_id, seat_id=seat_id)
                    observations.append(row)
                    journal.write(json.dumps(row) + '\n')
                    journal.flush()
        final = inventory(port)
        write_json(directory / 'inventory-after.json', final)
    result['sql_after'] = invariants(query)
    result['deployment_after'] = deployment(kube)
    reserved = [row for row in observations if row['outcome'] == 'RESERVED']
    observed_owners = {row['seat_id']: (row['request_id'], row['hold_id']) for row in reserved}
    stored_owners = {s['seat_id']: (s['held_by_request_id'], s['hold_id']) for s in final if s['state'] == 'HELD'}
    result['inventory'] = dict(before=len(initial), after=len(final),
        available_after=sum(s['state'] == 'AVAILABLE' for s in final),
        expected_first_fit_order=[r['seat_id'] for r in reserved] == expected_seats[:len(reserved)],
        owners_reconciled=([s['seat_id'] for s in final] == expected_seats
            and all(s['state'] in ('AVAILABLE', 'HELD') for s in final)
            and observed_owners == stored_owners and len(stored_owners) == len(reserved)
            and result['sql_after']['counts']['holds'] == result['sql_after']['counts']['held'] == len(reserved)))
    return (len(reserved) == WARMUP + MEASURED and result['sql_after']['status'] == 'PASS'
            and result['inventory']['expected_first_fit_order'] and result['inventory']['owners_reconciled']
            and result['deployment_before'] == result['deployment_after'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='New run ID, at most 100 characters')
    args = parser.parse_args()
    directory = run_directory(args.run)
    if any(directory.iterdir()):
        parser.error('Choose a new run ID')
    with (directory / 'experiment.json').open('x', encoding='utf-8') as marker:
        experiment = dict(case='TC-14 extended', run_id=args.run, started_at=utc(),
                          protocol=dict(trials=TRIALS, warmup_per_trial=WARMUP, measured_per_trial=MEASURED,
                                        concurrency=1, endpoint=ENDPOINT, section=SECTION, party_size=1,
                                        inventory_per_trial=ROWS * 10, timeout_seconds=TIMEOUT, hold_ttl_seconds=TTL))
        json.dump(experiment, marker, indent=2)
    results, observations = [], []
    try:
        local.preflight()
        experiment['host'] = host_metadata()
        write_json(directory / 'experiment.json', experiment)
        reference = None
        for number in range(1, TRIALS + 1):
            namespace = f'csc3104-tc14-{uuid4().hex[:16]}-t{number}'
            child = directory / f'trial-{number}'
            child.mkdir()
            rows = []
            result = dict(trial=number, namespace=namespace, started_at=utc(), status='INCOMPLETE')
            results.append(result)
            created = False
            print(f'Trial {number}/{TRIALS}: setting up {namespace}', flush=True)
            try:
                local.kubectl('create', 'namespace', namespace, namespace=None)
                created = True
                passed = trial(namespace, child, args.run, number, rows, result)
                configuration = result['deployment_before']['configuration']
                if reference is None:
                    reference = configuration
                result['configuration_matches_first'] = configuration == reference
                result['status'] = 'PASS' if passed and result['configuration_matches_first'] else 'FAIL'
            except (OSError, RuntimeError, ValueError) as exc:
                result['error'] = str(exc)
            finally:
                observations.extend(rows)
                result['measurement_finished_at'] = utc()
                write_json(child / 'trial.json', result)
                write_rows(directory, observations, 'raw-observations')
                if created:
                    try:
                        local.kubectl('delete', 'namespace', namespace, '--wait=true', '--timeout=180s', namespace=None)
                        (local.LOCAL / f'secrets-{namespace}.json').unlink(missing_ok=True)
                        result['cleanup'] = 'COMPLETE'
                    except (OSError, RuntimeError) as exc:
                        result.update(cleanup='FAILED', cleanup_error=str(exc))
                    write_json(child / 'trial.json', result)
            print(f'Trial {number}: {result["status"]} ({len(rows)} observations)', flush=True)
    finally:
        experiment['finished_at'] = utc()
        experiment['status'] = ('PASS' if len(results) == TRIALS and
            all(r['status'] == 'PASS' and r.get('cleanup') == 'COMPLETE' for r in results) else 'INCOMPLETE_OR_FAILED')
        write_json(directory / 'experiment.json', experiment)
    print(f'{experiment["status"]}: {directory}', flush=True)
    return 0 if experiment['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
