"""Durable queue with atomic claims, section rotation and fenced acknowledgements.

PostgreSQL is the shared backend for networked workers. SQLite is a local demo/test
backend only: independent processes must use the SAME file on one machine.
"""
import json
import uuid
import sqlite3
from contextlib import contextmanager


class Conflict(Exception):
    pass


class JobStore:
    def __init__(self, database_url):
        self.url = database_url
        self.sqlite = database_url.startswith("sqlite:///")
        if not self.sqlite and not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("Use postgresql://... or sqlite:///path for local demos")

    @contextmanager
    def transaction(self):
        if self.sqlite:
            conn = sqlite3.connect(self.url[len("sqlite:///"):], timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
        else:
            import psycopg
            from psycopg.rows import dict_row
            conn = psycopg.connect(self.url, row_factory=dict_row, connect_timeout=5)
        try:
            def execute(sql, params=()):
                return conn.execute(sql if self.sqlite else sql.replace("?", "%s"), params)
            # This row serializes short scheduling mutations, never remote calls.
            # It enforces a common section cursor and claim order across replicas.
            if not self.sqlite:
                execute("SELECT id FROM allocation_scheduler WHERE id=1 FOR UPDATE")
            yield execute
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self):
        statements = [
            "CREATE TABLE IF NOT EXISTS allocation_scheduler (id INTEGER PRIMARY KEY, last_section TEXT NOT NULL)",
            "INSERT INTO allocation_scheduler VALUES (1, '') ON CONFLICT (id) DO NOTHING",
            """CREATE TABLE IF NOT EXISTS allocation_batches (
                batch_id TEXT PRIMARY KEY, snapshot TEXT NOT NULL, orders TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS allocation_jobs (
                request_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, section TEXT NOT NULL,
                priority INTEGER NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, token TEXT, lease_until DOUBLE PRECISION,
                available_at DOUBLE PRECISION NOT NULL DEFAULT 0, result TEXT, error TEXT)""",
            """CREATE TABLE IF NOT EXISTS allocation_completions (
                batch_id TEXT PRIMARY KEY, payload TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0, token TEXT, lease_until DOUBLE PRECISION,
                available_at DOUBLE PRECISION NOT NULL DEFAULT 0, error TEXT)""",
            "CREATE INDEX IF NOT EXISTS allocation_ready ON allocation_jobs (state, section, priority)",
        ]
        # Bootstrap before transaction() can lock the scheduler row.
        if self.sqlite:
            conn = sqlite3.connect(self.url[len('sqlite:///'):])
        else:
            import psycopg
            conn = psycopg.connect(self.url, connect_timeout=5)
        try:
            for statement in statements:
                conn.execute(statement)
            conn.commit()
        finally:
            conn.close()
        # Upgrade existing local/shared queues too, including completed batches
        # created before completion notifications were introduced.
        with self.transaction() as execute:
            for row in execute("SELECT batch_id FROM allocation_batches").fetchall():
                self._queue_completion(execute, row["batch_id"])

    def _now(self, execute):
        sql = ("SELECT CAST(strftime('%s','now') AS REAL) AS now" if self.sqlite
               else "SELECT EXTRACT(EPOCH FROM clock_timestamp()) AS now")
        return float(execute(sql).fetchone()["now"])

    def submit(self, payload, orders, jobs):
        # Canonical snapshot makes response-loss retries idempotent.
        canonical = {**payload, "requests": sorted(payload["requests"], key=lambda p: p["global_position"])}
        snapshot = json.dumps(canonical, sort_keys=True)
        with self.transaction() as execute:
            previous = execute("SELECT snapshot FROM allocation_batches WHERE batch_id=?", (payload["batch_id"],)).fetchone()
            if previous:
                if previous["snapshot"] != snapshot:
                    raise Conflict("batch_id already exists with different input")
                return False
            if execute("SELECT 1 FROM allocation_jobs WHERE state NOT IN ('RESERVED','UNAVAILABLE','CANCELLED') LIMIT 1").fetchone():
                raise Conflict("Previous fixed batch is unfinished; retries/BLOCKED jobs also block admission")
            for job in jobs:
                if execute("SELECT 1 FROM allocation_jobs WHERE request_id=?", (job["request_id"],)).fetchone():
                    raise Conflict("request_id already belongs to an earlier batch; rejoin needs a new ID")
            execute("INSERT INTO allocation_batches VALUES (?,?,?)", (payload["batch_id"], snapshot, json.dumps(orders)))
            execute("UPDATE allocation_scheduler SET last_section='' WHERE id=1")
            for job in jobs:
                execute("""INSERT INTO allocation_jobs
                    (request_id,batch_id,section,priority,payload,state) VALUES (?,?,?,?,?,'QUEUED')""",
                        (job["request_id"], job["batch_id"], job["section"], job["priority"], json.dumps(job)))
            return True

    def claim(self, lease_seconds=30, max_attempts=5):
        with self.transaction() as execute:
            now = self._now(execute)
            execute("""UPDATE allocation_jobs SET state='RETRY', token=NULL, error='Worker lease expired'
                       WHERE state='IN_PROGRESS' AND lease_until<=?""", (now,))
            execute("""UPDATE allocation_jobs SET state='BLOCKED', error='Retry limit reached; reconcile manually'
                       WHERE state='RETRY' AND attempts>=?""", (max_attempts,))
            # Only the first unfinished party in each section is eligible. An
            # in-flight, retrying or blocked party prevents that section advancing.
            heads = execute("""SELECT j.* FROM allocation_jobs j
                WHERE j.state IN ('QUEUED','RETRY') AND j.available_at<=?
                AND NOT EXISTS (SELECT 1 FROM allocation_jobs earlier
                    WHERE earlier.batch_id=j.batch_id AND earlier.section=j.section
                    AND earlier.priority<j.priority AND earlier.state NOT IN ('RESERVED','UNAVAILABLE','CANCELLED'))
                ORDER BY j.section""", (now,)).fetchall()
            if not heads:
                return None
            last = execute("SELECT last_section FROM allocation_scheduler WHERE id=1").fetchone()["last_section"]
            chosen = next((j for j in heads if j["section"] > last), heads[0])
            token = str(uuid.uuid4())
            execute("""UPDATE allocation_jobs SET state='IN_PROGRESS', attempts=attempts+1,
                       token=?, lease_until=? WHERE request_id=?""", (token, now + lease_seconds, chosen["request_id"]))
            execute("UPDATE allocation_scheduler SET last_section=? WHERE id=1", (chosen["section"],))
            return {"job": json.loads(chosen["payload"]), "token": token, "attempts": chosen["attempts"] + 1}

    def finish(self, claim, result=None, error=None, retryable=True, max_attempts=5):
        with self.transaction() as execute:
            now = self._now(execute)
            if error is None:
                state = result["state"]
                if state not in ("RESERVED", "UNAVAILABLE"):
                    raise ValueError("Invalid terminal allocation outcome")
            else:
                state = "RETRY" if retryable and claim["attempts"] < max_attempts else "BLOCKED"
            # A late/stale worker cannot acknowledge a replacement worker's claim.
            updated = execute("""UPDATE allocation_jobs SET state=?, result=?, error=?, token=NULL,
                available_at=?, lease_until=NULL WHERE request_id=? AND token=?
                AND state='IN_PROGRESS' AND lease_until>?""",
                (state, json.dumps(result) if result else None, error,
                 now + min(2 ** claim["attempts"], 30), claim["job"]["request_id"], claim["token"], now))
            accepted = updated.rowcount == 1
            if accepted and error is None:
                self._queue_completion(execute, claim["job"]["batch_id"])
            return accepted

    def _queue_completion(self, execute, batch_id):
        rows = execute("SELECT state FROM allocation_jobs WHERE batch_id=?", (batch_id,)).fetchall()
        if not rows or any(r["state"] not in ("RESERVED", "UNAVAILABLE", "CANCELLED") for r in rows):
            return
        counts = {state: sum(r["state"] == state for r in rows)
                  for state in ("RESERVED", "UNAVAILABLE", "CANCELLED")}
        payload = {"event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, "allocation-complete:" + batch_id)),
                   "type": "batch.allocation_completed", "batch_id": batch_id,
                   "total_requests": len(rows), "outcomes": counts}
        # Same transaction as the final outcome: no crash window loses the event.
        execute("""INSERT INTO allocation_completions (batch_id,payload) VALUES (?,?)
                   ON CONFLICT (batch_id) DO NOTHING""", (batch_id, json.dumps(payload)))

    def claim_completion(self, lease_seconds=30):
        with self.transaction() as execute:
            now = self._now(execute)
            row = execute("""SELECT * FROM allocation_completions WHERE delivered=0
                AND available_at<=? AND (token IS NULL OR lease_until<=?)
                ORDER BY batch_id LIMIT 1""", (now, now)).fetchone()
            if row is None:
                return None
            token = str(uuid.uuid4())
            execute("""UPDATE allocation_completions SET token=?,lease_until=?,attempts=attempts+1
                WHERE batch_id=?""", (token, now + lease_seconds, row["batch_id"]))
            return {"payload": json.loads(row["payload"]), "token": token, "attempts": row["attempts"] + 1}

    def finish_completion(self, claim, error=None):
        with self.transaction() as execute:
            now = self._now(execute)
            updated = execute("""UPDATE allocation_completions SET delivered=?,error=?,token=NULL,
                lease_until=NULL,available_at=? WHERE batch_id=? AND token=? AND lease_until>?""",
                (int(error is None), error, now + min(2 ** min(claim["attempts"], 6), 60),
                 claim["payload"]["batch_id"], claim["token"], now))
            return updated.rowcount == 1

    def batch(self, batch_id):
        with self.transaction() as execute:
            batch = execute("SELECT orders FROM allocation_batches WHERE batch_id=?", (batch_id,)).fetchone()
            if batch is None:
                return None
            rows = execute("SELECT * FROM allocation_jobs WHERE batch_id=? ORDER BY section,priority", (batch_id,)).fetchall()
            jobs = [{**json.loads(row["payload"]), "state": row["state"], "attempts": row["attempts"],
                     "result": json.loads(row["result"]) if row["result"] else None, "error": row["error"]} for row in rows]
            event = execute("SELECT delivered FROM allocation_completions WHERE batch_id=?", (batch_id,)).fetchone()
            return {"batch_id": batch_id, "size_order": json.loads(batch["orders"]),
                    "completion_notification": ("delivered" if event["delivered"] else "pending") if event else "not_created",
                    "complete": all(j["state"] in ("RESERVED", "UNAVAILABLE", "CANCELLED") for j in jobs), "jobs": jobs}
