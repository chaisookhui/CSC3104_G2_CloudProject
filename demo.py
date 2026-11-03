"""Start the complete Docker project: python demo.py.

Creates ignored .env.core with random local credentials on first use. Existing
credentials, database volumes, queue entries and bookings are always preserved.
Requires Docker Desktop with Linux containers; Python uses only standard libraries.
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
    parser.add_argument('--port', type=int, help='Frontend loopback port for this run (default 18080)')
    parser.add_argument('--batch-size', type=int, help='Batch size for this run, from 1 to 100')
    args = parser.parse_args()
    if args.port is not None and not 1 <= args.port <= 65535:
        parser.error('--port must be from 1 to 65535')
    if args.batch_size is not None and not 1 <= args.batch_size <= 100:
        parser.error('--batch-size must be from 1 to 100')

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
