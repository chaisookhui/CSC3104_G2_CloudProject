"""Start the project: python demo.py [--kubernetes].

Creates ignored .env.core with random local credentials on first use. Existing
credentials, database volumes, queue entries and bookings are preserved on normal
startup. --kubernetes --reset-test-env explicitly clears only the lab testing area.
--kubernetes --reset-demo clears the main local Kubernetes demo on port 18090.
Requires Docker Desktop with Linux containers; Python uses only standard libraries.
The Kubernetes mode uses a dedicated Kind cluster and separate persistent data.
"""
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stop', action='store_true', help='Stop this project; preserve its data')
    parser.add_argument('--kubernetes', action='store_true', help='Deploy to the isolated local Kind cluster instead of Compose')
    parser.add_argument('--verify', action='store_true', help='With --kubernetes, run disposable booking/storage acceptance first')
    parser.add_argument('--reset-test-env', action='store_true',
                        help='With --kubernetes, erase and recreate ONLY csc3104-lab test data')
    parser.add_argument('--reset-demo', action='store_true',
                        help='With --kubernetes, erase and recreate the main demo at port 18090')
    parser.add_argument('--port', type=int, help='Frontend loopback port for this run (default 18080)')
    parser.add_argument('--batch-size', type=int, help='Batch size for this run, from 1 to 100')
    args = parser.parse_args()
    if args.reset_test_env and (not args.kubernetes or args.stop or args.verify or args.port is not None):
        parser.error('--reset-test-env requires --kubernetes and cannot be combined with --stop, --verify or --port')
    if args.reset_demo and (not args.kubernetes or args.reset_test_env or args.stop or args.verify or args.port is not None):
        parser.error('--reset-demo requires --kubernetes and cannot be combined with --reset-test-env, --stop, --verify or --port')
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error('--port must be from 1 to 65535')
    if args.batch_size is not None and not 1 <= args.batch_size <= 100:
        parser.error('--batch-size must be from 1 to 100')
    if args.verify and not args.kubernetes:
        parser.error('--verify requires --kubernetes')
    if args.kubernetes and args.port is not None:
        parser.error('Local Kubernetes uses loopback port 18090, configured in infra/k8s/kind.yaml')
    if args.kubernetes and args.stop:
        return subprocess.run([sys.executable, str(ROOT / 'infra/k8s/local.py'), '--stop'], cwd=ROOT).returncode
    if args.reset_test_env or args.reset_demo:
        reset_option = '--reset-demo' if args.reset_demo else '--reset-test-env'
        command = [sys.executable, str(ROOT / 'infra/k8s/local.py'), reset_option]
        if args.batch_size is not None:
            command += ['--batch-size', str(args.batch_size)]
        return subprocess.run(command, cwd=ROOT).returncode

    config = ROOT / '.env.core'
    if not config.exists():
        if args.stop:
            parser.error('No .env.core exists; there is no configured main stack to stop')
        with config.open('x', encoding='utf-8') as output:
            output.write('POSTGRES_PASSWORD=' + secrets.token_hex(24) + '\n'
                         'APP_DATABASE_PASSWORD=' + secrets.token_hex(24) + '\n'
                         'PAYMENT_API_TOKEN=' + secrets.token_hex(32) + '\n'
                         'FRONTEND_PORT=18080\nHOLD_TTL_SECONDS=300\nBATCH_SIZE=50\n')
        print('Created ignored .env.core with random local credentials.', flush=True)

    if args.kubernetes:
        command = [sys.executable, str(ROOT / 'infra/k8s/local.py')]
        if args.verify:
            command.append('--verify')
        if args.batch_size is not None:
            command += ['--batch-size', str(args.batch_size)]
        return subprocess.run(command, cwd=ROOT).returncode

    env = dict(os.environ)
    if args.port is not None:
        env['FRONTEND_PORT'] = str(args.port)
    if args.batch_size is not None:
        env['BATCH_SIZE'] = str(args.batch_size)
    command = ['docker', 'compose', '--env-file', str(config),
               '-f', str(ROOT / 'compose.core.yaml')]
    command += ['down'] if args.stop else ['up', '-d', '--build', '--wait', '--wait-timeout', '180']
    try:
        result = subprocess.run(command, cwd=ROOT, env=env)
    except FileNotFoundError:
        print('Docker was not found. Install/start Docker Desktop with Linux containers.', file=sys.stderr)
        return 1
    if result.returncode:
        print('Compose failed. Check the error above and the project logs; no data was reset.', file=sys.stderr)
        return result.returncode
    if args.stop:
        print('Stopped csc3104-core. Its PostgreSQL and Redis volumes are preserved.')
    else:
        print('csc3104-core is running. Open the frontend using its published port (default http://127.0.0.1:18080).')
        print('Stop with: python demo.py --stop. Bookings are preserved between runs.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
