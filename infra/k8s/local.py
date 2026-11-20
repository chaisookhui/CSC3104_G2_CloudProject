"""Deploy this project's existing images to an isolated local Kind cluster.

Invoked by python demo.py --kubernetes [--verify]. Secrets, tools and kubeconfig
stay in ignored .local. No global context changes, registry push or cloud service.
"""
import argparse
from functools import cache
import hashlib
import json
from pathlib import Path
import platform
import re
import secrets
import shutil
import ssl
import subprocess
import sys
import time
from urllib.request import urlopen
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / '.local' / 'k8s'
MANIFESTS = ROOT / 'infra' / 'k8s' / 'local'
KUBECONFIG = LOCAL / 'kubeconfig'
CLUSTER = 'csc3104'
CONTEXT = 'kind-csc3104'
NAMESPACE = 'csc3104'
TEST_NAMESPACE = 'csc3104-check'
LAB_NAMESPACE = 'csc3104-lab'
KIND_VERSION = 'v0.33.0'
KUBECTL_VERSION = 'v1.36.4'
# Published release checksums, rather than trusting tools already on PATH.
# https://github.com/kubernetes-sigs/kind/releases/tag/v0.33.0
# https://dl.k8s.io/release/v1.36.4/bin/<os>/<arch>/kubectl[.exe].sha256
TOOL_CHECKSUMS = {
    'windows-amd64': (
        '4b22adaa135368c5a465d56bbd8e520cbea87272a06ca00b6078e7b81515c9fc',
        '31947857be7583f3e4e6d889a3fb781ca813a45c20f11ccb3ef309714d01a9f3'),
    'linux-amd64': (
        'aee6151561422756b764a4ae28e7f44cda5af5a9eead3cc9985112b1de8d8e0d',
        '8b8f088da2dab964f853b38464033b1be15ede2839eca751482357c45abdd05a'),
    'linux-arm64': (
        '20022bee6cfcd5086cb7234d218e3454e6090022f2a8f55d1fa7fcf42c3867a2',
        '0ecf44450ee6063bf19dd166a103ee6df4a9034455c2abce626e6eea657d73fb'),
    'darwin-amd64': (
        '5a99f26f57246dc9319dd294803313197a0f34d33c525b3ea8b655db5916ece0',
        '71a3aa7c2ee2c974d9fbb462cba0c5c04a4df2e8d85eee94714fd819ea3c4e63'),
    'darwin-arm64': (
        '0c8c7dbe5e23594a198b786c4bc13dacc101fa6196b0cb0b23a1ca44e61f4b4f',
        'c9e4f713d6fee0043a3d835cca13077cda2bc0973840eb9779360df0b5bdfc69'),
}
IMAGES = ('ticketing-seat-store:local', 'ticketing-allocation:local',
          'ticketing-batch-dispatcher:local', 'ticketing-waiting-queue:local',
          'ticketing-payment:local', 'csc3104-frontend:local', 'postgres:17', 'redis:7-alpine')


def run(command, *, capture=False, source=None, check=True):
    result = subprocess.run([str(arg) for arg in command], cwd=ROOT, input=source,
                            text=True, capture_output=capture)
    if check and result.returncode:
        # Never include stdin here: it may contain a Secret resource.
        raise RuntimeError('Command failed: ' + ' '.join(str(x) for x in command))
    return result.stdout.strip() if capture else result.returncode


def kubectl(*args, namespace=NAMESPACE, capture=False, source=None, check=True):
    command = [kubectl_binary(), '--kubeconfig', KUBECONFIG, '--context', CONTEXT]
    if namespace:
        command += ['--namespace', namespace]
    return run(command + list(args), capture=capture, source=source, check=check)


def apply_object(value, namespace):
    kubectl('apply', '--server-side', '--field-manager=csc3104-local', '-f', '-',
            namespace=namespace, source=json.dumps(value))


def download_tool(url, destination):
    try:
        with urlopen(url, timeout=60) as response, destination.open('wb') as output:
            shutil.copyfileobj(response, output)
    except URLError as error:
        # Some older host Python builds cannot validate newer certificate chains
        # which Windows itself trusts. Native curl uses Windows' trust store;
        # TLS verification and the pinned SHA-256 check both remain mandatory.
        native_curl = shutil.which('curl.exe') if platform.system() == 'Windows' else None
        if not native_curl or not isinstance(error.reason, ssl.SSLCertVerificationError):
            raise RuntimeError('Could not download ' + url +
                               '. Check internet access and trusted proxy certificates.') from error
        result = subprocess.run([native_curl, '--fail', '--location', '--silent', '--show-error',
                                 '--connect-timeout', '15', '--max-time', '120',
                                 '--output', str(destination), url])
        if result.returncode:
            raise RuntimeError('Could not download ' + url + '. Check internet/proxy settings.')


@cache
def tool_binary(name):
    system = platform.system().lower()
    architecture = {'x86_64': 'amd64', 'amd64': 'amd64',
                    'aarch64': 'arm64', 'arm64': 'arm64'}.get(platform.machine().lower())
    target = f'{system}-{architecture}'
    if target not in TOOL_CHECKSUMS:
        raise RuntimeError('Unsupported host: ' + target + '. See infra/k8s/README.md.')
    version = KIND_VERSION if name == 'kind' else KUBECTL_VERSION
    expected = TOOL_CHECKSUMS[target][0 if name == 'kind' else 1]
    suffix = '.exe' if system == 'windows' else ''
    executable = ROOT / '.local' / 'bin' / f'{name}-{version}-{target}{suffix}'
    previous = executable.parent / (name + suffix)
    if not executable.exists() and previous.exists() and (
            hashlib.sha256(previous.read_bytes()).hexdigest() == expected):
        shutil.copyfile(previous, executable)
    if not executable.exists():
        executable.parent.mkdir(parents=True, exist_ok=True)
        url = (f'https://github.com/kubernetes-sigs/kind/releases/download/{version}/kind-{target}'
               if name == 'kind' else
               f'https://dl.k8s.io/release/{version}/bin/{system}/{architecture}/kubectl{suffix}')
        print(f'Preparing project-local {name} {version} ({target})...', flush=True)
        temporary = executable.with_name(executable.name + '.download')
        try:
            download_tool(url, temporary)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != expected:
                raise RuntimeError(f'{name} download failed its official {version} checksum')
            temporary.replace(executable)
        finally:
            temporary.unlink(missing_ok=True)
    if hashlib.sha256(executable.read_bytes()).hexdigest() != expected:
        raise RuntimeError(f'Project-local {name} failed its official {version} checksum: {executable}')
    if system != 'windows':
        executable.chmod(0o755)
    return executable


def kind_binary():
    return tool_binary('kind')


def kubectl_binary():
    return tool_binary('kubectl')


def version_numbers(value):
    match = re.match(r'v?(\d+)\.(\d+)', value)
    if not match:
        raise RuntimeError('Could not identify version: ' + value)
    return tuple(map(int, match.groups()))


def preflight():
    if not shutil.which('docker'):
        raise RuntimeError('Docker was not found. Install Docker Desktop with Linux containers or Docker Engine 24+.')
    try:
        info = json.loads(run(['docker', 'info', '--format', '{{json .}}'], capture=True))
    except (RuntimeError, ValueError) as error:
        raise RuntimeError('Cannot reach Docker. Start Docker Desktop with Linux containers and retry.') from error
    if info.get('OSType') != 'linux':
        raise RuntimeError('This demo needs Linux containers. Switch Docker Desktop to Linux containers.')
    if version_numbers(info.get('ServerVersion', 'unknown')) < (24, 0):
        raise RuntimeError('This demo supports Docker Engine 24.0+. Your engine is ' + info['ServerVersion'])
    if info.get('NCPU', 0) < 2 or info.get('MemTotal', 0) < 4 * 1024**3:
        raise RuntimeError('Give Docker at least 2 CPUs and 4 GiB RAM (8 GiB recommended), then retry.')
    try:
        compose = run(['docker', 'compose', 'version', '--short'], capture=True)
    except RuntimeError as error:
        raise RuntimeError('Docker Compose v2.20+ is required; install the Docker Compose plugin.') from error
    if version_numbers(compose) < (2, 20):
        raise RuntimeError('Docker Compose v2.20+ is required. Your version is ' + compose)
    cgroup = str(info.get('CgroupVersion', 'unknown'))
    if cgroup not in ('1', '2'):
        raise RuntimeError('Docker did not report a supported cgroup version (1 or 2).')
    print(f'Docker {info["ServerVersion"]}, Compose {compose}, cgroup v{cgroup}: prerequisites passed.', flush=True)
    if cgroup == '1':
        print('Using local-demo cgroup v1 compatibility; host settings are unchanged.', flush=True)


def cluster(kind):
    names = run([kind, 'get', 'clusters'], capture=True).splitlines()
    if CLUSTER not in names:
        try:
            run([kind, 'create', 'cluster', '--name', CLUSTER, '--config', ROOT / 'infra/k8s/kind.yaml',
                 '--kubeconfig', KUBECONFIG, '--wait', '300s', '--retain'])
        except RuntimeError as error:
            logs = LOCAL / ('startup-logs-' + time.strftime('%Y%m%d-%H%M%S'))
            run([kind, 'export', 'logs', logs, '--name', CLUSTER], check=False)
            raise RuntimeError(f'Cluster startup failed. The node was retained; inspect {logs}. '
                               'See infra/k8s/README.md for recovery; no data was deleted.') from error
    # Refresh this checkout's endpoint even when a stale kubeconfig already exists.
    run([kind, 'export', 'kubeconfig', '--name', CLUSTER, '--kubeconfig', KUBECONFIG])
    kubectl('wait', '--for=condition=Ready', 'nodes', '--all', '--timeout=300s', namespace=None)
    kubectl('rollout', 'status', 'deployment/coredns', '--timeout=300s', namespace='kube-system')


def load_images(kind):
    # Modern containerd image stores need a platform-specific export. Older
    # classic Docker stores already contain just the local platform and do not
    # support --platform on image save (added in Engine API 1.48).
    architecture = kubectl('get', 'nodes', '-o', 'jsonpath={.items[0].status.nodeInfo.architecture}',
                           namespace=None, capture=True)
    if architecture not in ('amd64', 'arm64'):
        raise RuntimeError('Unsupported local node architecture: ' + architecture)
    archive = LOCAL / 'images.tar'
    try:
        api = run(['docker', 'version', '--format', '{{.Server.APIVersion}}'], capture=True)
        help_text = run(['docker', 'image', 'save', '--help'], capture=True)
        options = ['--platform', 'linux/' + architecture] if (
            version_numbers(api) >= (1, 48) and '--platform' in help_text) else []
        print('Loading local images using ' + ('platform-specific' if options else 'legacy-compatible') +
              ' Docker export...', flush=True)
        run(['docker', 'image', 'save', *options, '--output', archive, *IMAGES])
        run([kind, 'load', 'image-archive', archive, '--name', CLUSTER])
    finally:
        archive.unlink(missing_ok=True)


def configuration(namespace):
    path = LOCAL / ('secrets-' + namespace + '.json')
    if path.exists():
        values = json.loads(path.read_text())
    else:
        password = secrets.token_hex(24)
        values = {'POSTGRES_PASSWORD': secrets.token_hex(24), 'APP_DATABASE_PASSWORD': password,
                  'PAYMENT_API_TOKEN': secrets.token_hex(32)}
        for key, role, database in (
            ('SEAT_DATABASE_URL', 'seat_service', 'seats'),
            ('ALLOCATION_DATABASE_URL', 'allocation_service', 'allocation'),
            ('DISPATCHER_DATABASE_URL', 'dispatcher_service', 'dispatcher'),
            ('PAYMENT_DATABASE_URL', 'payment_service', 'payment')):
            values[key] = f'postgresql://{role}:{password}@postgres:5432/{database}'
        with path.open('x', encoding='utf-8') as output:
            json.dump(values, output)
    apply_object({'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'core-secrets'},
                  'type': 'Opaque', 'stringData': values}, namespace)
    apply_object({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'database-bootstrap'},
                  'data': {'init-db.sh': (ROOT / 'infra/docker/init-core-db.sh').read_text()}}, namespace)


def deploy(namespace, hold_ttl=300, batch_size=50, policy='demand-cycle'):
    if policy not in ('demand-cycle', 'fcfs') or (policy != 'demand-cycle' and namespace not in (LAB_NAMESPACE, TEST_NAMESPACE)):
        raise ValueError('FCFS experiments are restricted to the lab or disposable verification namespace')
    apply_object({'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': namespace,
                  'labels': {'app.kubernetes.io/part-of': 'csc3104'}}}, None)
    configuration(namespace)
    kubectl('apply', '-f', MANIFESTS / 'config.yaml', namespace=namespace)
    kubectl('patch', 'configmap', 'core-config', '--type=merge', '-p',
            json.dumps({'data': {'HOLD_TTL_SECONDS': str(hold_ttl), 'BATCH_SIZE': str(batch_size),
                                'ALLOCATION_POLICY': policy, 'EXPERIMENT_NAMESPACE': namespace}}), namespace=namespace)
    kubectl('apply', '-f', MANIFESTS / 'storage.yaml', namespace=namespace)
    for name in ('postgres', 'redis'):
        kubectl('rollout', 'status', 'statefulset/' + name, '--timeout=180s', namespace=namespace)

    # A Ready node/storage Pod does not imply that service DNS has synchronized.
    # Wait again here in case the host restarted during a long image build/load.
    kubectl('rollout', 'status', 'deployment/coredns', '--timeout=300s', namespace='kube-system')
    # Init jobs are replayable, but never interrupt a currently running migration.
    for name in ('seat-init', 'allocation-init', 'payment-migrate'):
        existing = kubectl('get', 'job', name, '--ignore-not-found', '-o', 'json', namespace=namespace, capture=True)
        if existing and json.loads(existing).get('status', {}).get('active', 0):
            raise RuntimeError('A migration job is already active: ' + name)
    kubectl('delete', 'job', 'seat-init', 'allocation-init', 'payment-migrate', '--ignore-not-found', namespace=namespace)
    kubectl('apply', '-f', MANIFESTS / 'jobs.yaml', namespace=namespace)
    kubectl('wait', '--for=condition=complete', 'job/seat-init', 'job/allocation-init',
            'job/payment-migrate', '--timeout=180s', namespace=namespace)
    existing_deployments = kubectl('get', 'deployments', '-o', 'jsonpath={.items[*].metadata.name}',
                                  namespace=namespace, capture=True).split()
    for filename in ('services.yaml', 'apis.yaml', 'workers.yaml'):
        kubectl('apply', '-f', MANIFESTS / filename, namespace=namespace)
    # Makes redeployments pick up image/config changes without losing stored data.
    if existing_deployments:
        kubectl('rollout', 'restart', *('deployment/' + name for name in existing_deployments), namespace=namespace)
    names = kubectl('get', 'deployments', '-o', 'jsonpath={.items[*].metadata.name}',
                    namespace=namespace, capture=True).split()
    for name in names:
        kubectl('rollout', 'status', 'deployment/' + name, '--timeout=180s', namespace=namespace)


def verify_storage(namespace):
    def read():
        data = {}
        for key, database, query in (
            ('holds', 'seats', "SELECT json_agg(json_build_object('request_id',request_id,'hold_id',hold_id,'status',status) ORDER BY request_id) FROM holds"),
            ('seats', 'seats', "SELECT count(*) FROM seats WHERE state='CONFIRMED'"),
            ('payments', 'payment', "SELECT json_agg(json_build_object('payment_id',payment_id,'status',status,'attempt_status',attempt_status) ORDER BY payment_id) FROM wy_payments")):
            data[key] = json.loads(kubectl('exec', 'postgres-0', '--', 'psql', '-U', 'postgres',
                '-d', database, '-tAc', query, namespace=namespace, capture=True))
        queue = json.loads(kubectl('exec', 'redis-0', '--', 'redis-cli', '--json', 'HGETALL',
            'ticketing:kubernetes:queue:v2:requests', namespace=namespace, capture=True))
        data['queue'] = dict(zip(queue[::2], queue[1::2])) if isinstance(queue, list) else queue
        claims = json.loads(kubectl('get', 'pvc', '-o', 'json', namespace=namespace, capture=True))
        data['claims'] = {p['metadata']['name']: p['metadata']['uid'] for p in claims['items']}
        return data

    before = read()
    assert len(before['holds']) == 6 and before['seats'] == 4 and len(before['payments']) == 3
    kubectl('delete', 'pod', 'postgres-0', 'redis-0', '--wait=true', namespace=namespace)
    for name in ('postgres', 'redis'):
        kubectl('rollout', 'status', 'statefulset/' + name, '--timeout=180s', namespace=namespace)
    deadline = time.monotonic() + 90
    while True:
        try:
            after = read()
            break
        except RuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)
    assert before == after, 'Booking records or PVC identities changed after storage Pod replacement'
    print('PASS: PostgreSQL bookings/payment history and Redis queue survived storage Pod replacement on the same PVCs', flush=True)


def verify():
    if kubectl('get', 'namespace', TEST_NAMESPACE, '--ignore-not-found', '-o', 'name',
               namespace=None, capture=True):
        raise RuntimeError('Existing csc3104-check namespace found; inspect it before reusing the disposable test name')
    try:
        deploy(TEST_NAMESPACE, hold_ttl=30)
        kubectl('exec', '-i', 'deployment/frontend', '--', 'python', '-',
                '--base-url', 'http://127.0.0.1:8080', '--allow-bookings', '--timeout', '90',
                namespace=TEST_NAMESPACE, source=(ROOT / 'tests/docker_booking_smoke.py').read_text())
        verify_storage(TEST_NAMESPACE)
    finally:
        # --verify explicitly opts into disposable test data; main PVCs are separate.
        kubectl('delete', 'namespace', TEST_NAMESPACE, '--ignore-not-found', '--timeout=120s', namespace=None)
        secret_file = LOCAL / ('secrets-' + TEST_NAMESPACE + '.json')
        secret_file.unlink(missing_ok=True)


def _reset_environment(namespace, batch_size):
    # Only these two local targets are supported; no arbitrary namespace input.
    if namespace not in (NAMESPACE, LAB_NAMESPACE):
        raise ValueError('Reset supports only the main local demo or the lab')
    # Namespace deletion stops all writers and removes the target PVCs together.
    # If it fails/times out, retain credentials and do not recreate anything.
    print(f'Resetting ONLY {namespace}: deleting demo bookings, payments, queue and storage.', flush=True)
    kubectl('delete', 'namespace', namespace, '--ignore-not-found',
            '--wait=true', '--timeout=180s', namespace=None)
    (LOCAL / ('secrets-' + namespace + '.json')).unlink(missing_ok=True)
    deploy(namespace, hold_ttl=300, batch_size=batch_size)


def expose_main_frontend():
    kubectl('patch', 'service', 'frontend', '--type=merge', '-p', json.dumps({'spec': {
        'type': 'NodePort', 'ports': [{'name': 'http', 'port': 8080, 'targetPort': 'http', 'nodePort': 30080}]}}),
        namespace=NAMESPACE)


def reset_demo(batch_size=50):
    _reset_environment(NAMESPACE, batch_size)
    expose_main_frontend()
    print('Fresh main demo ready: http://127.0.0.1:18090 (pre-sale, initial seats, empty queue).', flush=True)
    print('Reload the page and click My booking > New user before registering again. The lab and Docker Compose data are unchanged.')


def reset_test_environment(batch_size=50):
    _reset_environment(LAB_NAMESPACE, batch_size)
    print('Fresh lab ready: pre-sale, initial seats, no previous bookings or payments.', flush=True)
    print('Restart the lab port-forward in Terminal B, then open http://127.0.0.1:18100.')
    print('In the browser, click My booking > New user, then register again.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check Docker and prepare pinned tools without deploying')
    parser.add_argument('--verify', action='store_true', help='Run booking/storage acceptance in a disposable namespace')
    parser.add_argument('--stop', action='store_true', help='Scale this project to zero, preserving PVCs and secrets')
    parser.add_argument('--reset-test-env', action='store_true', help='Erase and recreate only the csc3104-lab testing area')
    parser.add_argument('--reset-demo', action='store_true', help='Erase and recreate the main local demo at port 18090')
    parser.add_argument('--batch-size', type=int, default=50)
    args = parser.parse_args()
    if args.check and (args.stop or args.verify or args.reset_test_env or args.reset_demo):
        parser.error('--check cannot be combined with deployment or reset options')
    if args.reset_test_env and (args.stop or args.verify):
        parser.error('--reset-test-env cannot be combined with --stop or --verify')
    if args.reset_demo and (args.reset_test_env or args.stop or args.verify):
        parser.error('--reset-demo cannot be combined with --reset-test-env, --stop or --verify')
    if not 1 <= args.batch_size <= 100:
        parser.error('--batch-size must be 1 to 100')
    LOCAL.mkdir(parents=True, exist_ok=True)
    preflight()
    kubectl_binary()
    if args.check:
        kind_binary()
        print('Kubernetes prerequisites ready. Start with python demo.py --kubernetes.', flush=True)
        return
    if args.reset_test_env or args.reset_demo:
        if not KUBECONFIG.exists():
            raise RuntimeError('Start the local cluster first with python demo.py --kubernetes')
        kubectl('wait', '--for=condition=Ready', 'nodes', '--all', '--timeout=180s', namespace=None)
        reset = reset_demo if args.reset_demo else reset_test_environment
        reset(batch_size=args.batch_size)
        return
    if args.stop:
        kubectl('scale', 'deployment', '--all', '--replicas=0')
        kubectl('scale', 'statefulset', '--all', '--replicas=0')
        print('Stopped csc3104 application/storage Pods; PVCs and secrets are preserved.')
        return
    kind = kind_binary()
    # Discover host/cluster failures before spending time building the app.
    cluster(kind)
    run(['docker', 'compose', '--env-file', ROOT / '.env.core', '-f', ROOT / 'compose.core.yaml', 'build'])
    for image in ('postgres:17', 'redis:7-alpine'):
        if not json.loads(run(['docker', 'image', 'inspect', image], capture=True, check=False) or '[]'):
            run(['docker', 'pull', image])
    load_images(kind)
    if args.verify:
        verify()
    deploy(NAMESPACE, batch_size=args.batch_size)
    expose_main_frontend()
    kubectl('get', 'pods,pvc,services')
    print('Local Kubernetes is ready: http://127.0.0.1:18090', flush=True)
    print('State survives Pod replacement, but deleting the Kind cluster also deletes its local storage.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, AssertionError, OSError) as error:
        print('Kubernetes deployment failed: ' + str(error), file=sys.stderr)
        print('See infra/k8s/README.md for the project-local kubectl command and startup diagnostics.', file=sys.stderr)
        sys.exit(1)
