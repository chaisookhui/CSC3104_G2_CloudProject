"""Shared fixed-window API admission, separate from durable payment processing."""


def consume_rate(database, scope, limit, window_seconds):
    with database.connect() as conn:
        conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('wy-rate:' + scope,))
        now = conn.execute('SELECT EXTRACT(EPOCH FROM clock_timestamp()) AS now').fetchone()['now']
        window_id = int(now // window_seconds)
        row = conn.execute('''INSERT INTO wy_rate_limits(scope,window_id,requests) VALUES (%s,%s,1)
            ON CONFLICT(scope) DO UPDATE SET window_id=EXCLUDED.window_id,
            requests=CASE WHEN wy_rate_limits.window_id!=EXCLUDED.window_id THEN 1
                          ELSE wy_rate_limits.requests+1 END
            WHERE wy_rate_limits.window_id!=EXCLUDED.window_id OR wy_rate_limits.requests<%s
            RETURNING requests''', (scope,window_id,limit)).fetchone()
    return row is not None, max(1, int((window_id+1)*window_seconds-now)+1)
