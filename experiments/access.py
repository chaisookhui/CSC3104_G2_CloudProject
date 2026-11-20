"""Print the local administrator password, without exposing the internal service token."""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace',choices=['csc3104','csc3104-lab','csc3104-check'],default='csc3104-lab')
    parser.add_argument('--compose',action='store_true',help='Read generated .env.core instead of a Kubernetes namespace')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    if args.compose:
        values=dict(line.split('=',1) for line in (root/'.env.core').read_text().splitlines() if '=' in line and not line.startswith('#'))
        token=os.getenv('PAYMENT_API_TOKEN') or values['PAYMENT_API_TOKEN'].strip().strip('\"\'')
    else:
        path=root/'.local/k8s'/('secrets-'+args.namespace+'.json')
        token=json.loads(path.read_text())['PAYMENT_API_TOKEN']
    print(hmac.new(token.encode(),b'csc3104:admin-password',hashlib.sha256).hexdigest())
