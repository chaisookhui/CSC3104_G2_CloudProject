"""Independent configuration. Environment overrides this service's optional .env."""
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv


def settings():
    load_dotenv(Path(__file__).with_name('.env'), override=False)
    dsn = os.getenv('PAYMENT_DATABASE_URL') or os.getenv('DATABASE_URL')
    if not dsn:
        raise ValueError('Set PAYMENT_DATABASE_URL in the environment or payment .env')
    result = {
        'database_url': dsn,
        'seat_url': os.getenv('SEAT_STORE_URL', 'http://127.0.0.1:5003').rstrip('/'),
        'cancel_path': os.getenv('SEAT_CANCEL_PATH', '/seats/cancel'),
        'status_url': os.getenv('PAYMENT_STATUS_URL', ''),
        'host': os.getenv('PAYMENT_HOST', '127.0.0.1'),
        'port': int(os.getenv('PAYMENT_PORT', '5004')),
        'interval': float(os.getenv('PAYMENT_WORKER_INTERVAL', '1')),
        'timeout': float(os.getenv('PAYMENT_HTTP_TIMEOUT', '5')),
        'api_token': os.getenv('PAYMENT_API_TOKEN', ''),
        'require_auth': os.getenv('PAYMENT_REQUIRE_AUTH', 'false').lower(),
        'threads': int(os.getenv('PAYMENT_HTTP_THREADS', '8')),
        'connection_limit': int(os.getenv('PAYMENT_HTTP_CONNECTION_LIMIT', '100')),
        'rate_limit': int(os.getenv('PAYMENT_RATE_LIMIT', '600')),
        'rate_window': int(os.getenv('PAYMENT_RATE_WINDOW_SECONDS', '60')),
        'max_pending': int(os.getenv('PAYMENT_MAX_PENDING', '5000')),
        'max_attempts_per_hold': int(os.getenv('PAYMENT_MAX_ATTEMPTS_PER_HOLD', '10')),
        'checkout_key': os.getenv('PAYMENT_CHECKOUT_SIGNING_KEY',''),
        'customer_outcome': os.getenv('PAYMENT_CUSTOMER_MOCK_OUTCOME','success'),
    }
    for name in ('seat_url', 'status_url'):
        value = result[name]
        if value and (urlparse(value).scheme not in ('http', 'https') or not urlparse(value).netloc):
            raise ValueError(f'{name} must be an HTTP(S) URL')
    if result['cancel_path'] and not result['cancel_path'].startswith('/'):
        raise ValueError('SEAT_CANCEL_PATH must be an absolute service path')
    if result['interval'] <= 0 or result['timeout'] <= 0 or not 1 <= result['port'] <= 65535:
        raise ValueError('Invalid payment timeout, interval or port')
    if result['require_auth'] not in ('true', 'false'):
        raise ValueError('PAYMENT_REQUIRE_AUTH must be true or false')
    result['require_auth'] = result['require_auth'] == 'true'
    if result['require_auth'] and len(result['api_token']) < 32:
        raise ValueError('Authenticated deployment requires PAYMENT_API_TOKEN of at least 32 characters')
    if any(result[k] < 1 for k in ('threads','connection_limit','rate_limit','rate_window','max_pending','max_attempts_per_hold')):
        raise ValueError('HTTP and rate-limit bounds must be positive')
    if result['checkout_key'] and (len(result['checkout_key'])<32 or result['checkout_key']==result['api_token']):
        raise ValueError('Use a separate checkout signing key of at least 32 characters')
    if result['customer_outcome'] not in ('success','decline','timeout'):
        raise ValueError('Invalid server-side customer mock outcome')
    return result
