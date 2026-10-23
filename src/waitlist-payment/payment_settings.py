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
        'cancel_path': os.getenv('SEAT_CANCEL_PATH', ''),
        'status_url': os.getenv('PAYMENT_STATUS_URL', ''),
        'host': os.getenv('PAYMENT_HOST', '127.0.0.1'),
        'port': int(os.getenv('PAYMENT_PORT', '5004')),
        'interval': float(os.getenv('PAYMENT_WORKER_INTERVAL', '1')),
        'timeout': float(os.getenv('PAYMENT_HTTP_TIMEOUT', '5')),
        'api_token': os.getenv('PAYMENT_API_TOKEN', ''),
    }
    for name in ('seat_url', 'status_url'):
        value = result[name]
        if value and (urlparse(value).scheme not in ('http', 'https') or not urlparse(value).netloc):
            raise ValueError(f'{name} must be an HTTP(S) URL')
    if result['cancel_path'] and not result['cancel_path'].startswith('/'):
        raise ValueError('SEAT_CANCEL_PATH must be an absolute service path')
    if result['interval'] <= 0 or result['timeout'] <= 0 or not 1 <= result['port'] <= 65535:
        raise ValueError('Invalid payment timeout, interval or port')
    return result
