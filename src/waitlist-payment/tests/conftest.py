"""Payment-owned tests: disposable schemas in a real dedicated PostgreSQL DB."""
import os
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from dotenv import load_dotenv
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from payment_db import Database
from lifecycle import Lifecycle


@pytest.fixture
def db():
    # Test-only reuse of local test configuration; runtime never reads seat-store .env.
    load_dotenv(ROOT.parent / 'seat-store' / '.env', override=False)
    dsn = os.getenv('PAYMENT_TEST_DATABASE_URL') or os.getenv('TEST_DATABASE_URL')
    if not dsn or not conninfo_to_dict(dsn).get('dbname', '').endswith('_test'):
        pytest.fail('Set PAYMENT_TEST_DATABASE_URL to a dedicated *_test database')
    name = 'payment_test_' + uuid4().hex
    with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(name)))
    try:
        yield Database(dsn, name)
    finally:
        with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
            conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(name)))


@pytest.fixture
def lifecycle(db, seats):
    result = Lifecycle(db, seats)
    result.initialize()
    return result
