"""Payment-owned PostgreSQL access; no imports or writes into seat-store."""
import re
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row


class Database:
    def __init__(self, dsn, schema=None):
        if schema and not re.fullmatch(r'[a-z][a-z0-9_]*', schema):
            raise ValueError('Invalid schema')
        self.dsn, self.schema = dsn, schema

    @contextmanager
    def connect(self):
        options = '-c lock_timeout=5000 -c statement_timeout=15000 -c timezone=UTC'
        if self.schema:
            options += f' -c search_path={self.schema}'
        with psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5,
                             options=options) as conn:
            yield conn
