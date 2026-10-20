"""Integration tests use disposable schemas in a separate *_test database."""

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
load_dotenv(ROOT / ".env", override=False)

from app import create_app
from db import Database
from store import SeatStore


@pytest.fixture
def db():
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn or not conninfo_to_dict(dsn).get("dbname", "").endswith("_test"):
        pytest.fail("Set TEST_DATABASE_URL to a dedicated database ending in _test; run setup.ps1.")
    schema = "test_" + uuid4().hex
    unavailable = None
    try:
        with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
            conn.execute(sql.SQL("CREATE SCHEMA {} ").format(sql.Identifier(schema)))
    except psycopg.Error as error:
        unavailable = type(error).__name__
    if unavailable:
        pytest.fail(f"Test PostgreSQL is unavailable ({unavailable}); run setup.ps1.", pytrace=False)
    database = Database(dsn, schema=schema)
    try:
        database.migrate()
        database.seed("dev")
        yield database
    finally:
        with psycopg.connect(dsn, autocommit=True, connect_timeout=5) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.fixture
def store(db):
    return SeatStore(db, hold_ttl=300)


@pytest.fixture
def app(db):
    return create_app({"TESTING": True, "DATABASE_URL": db.dsn, "DATABASE": db})


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def make_due(db):
    def expire(hold_id):
        with db.connect() as conn:
            conn.execute("UPDATE holds SET hold_expiry = clock_timestamp() - INTERVAL '1 second' "
                         "WHERE hold_id = %s", (hold_id,))
    return expire

