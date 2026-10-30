"""Payment-owned PostgreSQL access; no imports or writes into seat-store."""
import re
import atexit
import os
from contextlib import contextmanager
from threading import Lock

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class Database:
    def __init__(self, dsn, schema=None, *, max_size=None, timeout=None, max_waiting=None):
        if schema and not re.fullmatch(r'[a-z][a-z0-9_]*', schema):
            raise ValueError('Invalid schema')
        self.dsn, self.schema = dsn, schema
        self.max_size = int(max_size if max_size is not None else os.getenv('PAYMENT_DB_POOL_SIZE', '8'))
        self.timeout = float(timeout if timeout is not None else os.getenv('PAYMENT_DB_POOL_TIMEOUT', '3'))
        self.max_waiting = int(max_waiting if max_waiting is not None else os.getenv('PAYMENT_DB_POOL_WAITING', '16'))
        if self.max_size < 1 or self.timeout <= 0 or self.max_waiting < 1:
            raise ValueError('Payment pool bounds must be positive')
        self._pool = None
        self._pool_lock = Lock()
        atexit.register(self.close)

    def close(self):
        with self._pool_lock:
            if self._pool is not None:
                self._pool.close()

    def _get_pool(self):
        # Lazy creation keeps imports/app factories free of connections and threads.
        with self._pool_lock:
            if self._pool is None:
                options = '-c lock_timeout=5000 -c statement_timeout=15000 -c timezone=UTC'
                if self.schema:
                    options += f' -c search_path={self.schema}'
                self._pool = ConnectionPool(self.dsn, min_size=0, max_size=self.max_size,
                    timeout=self.timeout, max_waiting=self.max_waiting, open=True,
                    kwargs={'row_factory': dict_row, 'connect_timeout': 5, 'options': options})
            return self._pool

    @contextmanager
    def connect(self):
        # connection() commits/rolls back before returning the connection to the pool.
        with self._get_pool().connection() as conn:
            yield conn
