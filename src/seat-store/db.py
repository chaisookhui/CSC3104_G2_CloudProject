"""Short-lived connections, transactional migrations and non-destructive seeding."""

import hashlib
import re
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from settings import ROOT, SEAT_MAPS


class Database:
    def __init__(self, dsn, schema=None):
        self.dsn = dsn
        if schema and not re.fullmatch(r"[a-z][a-z0-9_]*", schema):
            raise ValueError("Invalid schema name")
        self.schema = schema

    @contextmanager
    def connect(self):
        options = "-c lock_timeout=5000 -c statement_timeout=15000 -c timezone=UTC"
        if self.schema:
            options += f" -c search_path={self.schema}"
        with psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5,
                             options=options) as conn:
            yield conn

    def migrate(self):
        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(3104003)")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    name TEXT PRIMARY KEY, checksum TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
                )
            """)
            for path in sorted((ROOT / "database" / "migrations").glob("*.sql")):
                source = path.read_text(encoding="utf-8")
                checksum = hashlib.sha256(source.encode()).hexdigest()
                previous = conn.execute(
                    "SELECT checksum FROM schema_migrations WHERE name = %s", (path.name,)
                ).fetchone()
                if previous:
                    if previous["checksum"] != checksum:
                        raise ValueError(f"Applied migration changed: {path.name}")
                    continue
                conn.execute(source)
                conn.execute("INSERT INTO schema_migrations(name, checksum) VALUES (%s, %s)",
                             (path.name, checksum))

    def seed(self, tier="dev"):
        if tier not in SEAT_MAPS:
            raise ValueError("Seat map tier must be dev or eval")
        expected = SEAT_MAPS[tier]
        with self.connect() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(3104003)")
            existing = conn.execute("SELECT section, row_count FROM sections").fetchall()
            if existing:
                if {row["section"]: row["row_count"] for row in existing} != expected:
                    raise ValueError("Existing seat map differs. Use a separate database for another tier.")
                return
            for section, rows in expected.items():
                conn.execute("INSERT INTO sections VALUES (%s, %s, 10)", (section, rows))
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO seats(seat_id, section, row, position_in_row) "
                        "VALUES (%s, %s, %s, %s)",
                        [(f"{section}-{row}-{pos}", section, row, pos)
                         for row in range(1, rows + 1) for pos in range(1, 11)],
                    )

