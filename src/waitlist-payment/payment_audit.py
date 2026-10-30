"""Allowlisted durable business audit records; never store bodies, credentials or cards."""
from uuid import uuid4

from psycopg.types.json import Jsonb


def record(conn, action, *, actor='system', request_id=None, hold_id=None,
           entity_id=None, **details):
    conn.execute('''INSERT INTO wy_audit(audit_id,action,actor,request_id,hold_id,entity_id,details)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)''',
                 (uuid4(), action, actor, request_id, hold_id,
                  str(entity_id) if entity_id is not None else None, Jsonb(details)))
