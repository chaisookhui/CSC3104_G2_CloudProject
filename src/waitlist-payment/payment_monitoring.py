"""Per-process HTTP metrics plus durable shared backlog/worker observations."""
from collections import defaultdict
from threading import Lock


class HttpMetrics:
    def __init__(self):
        self.lock = Lock()
        self.requests = defaultdict(int)
        self.latency = defaultdict(lambda: [0, 0.0, 0.0])

    def observe(self, endpoint, status, elapsed):
        # endpoint is Flask's fixed route name, never a request/hold ID or URL.
        with self.lock:
            self.requests[endpoint, status] += 1
            item = self.latency[endpoint]
            item[0] += 1
            item[1] += elapsed
            item[2] = max(item[2], elapsed)

    def render(self):
        lines = ['# TYPE payment_http_requests_total counter']
        with self.lock:
            for (endpoint, status), count in sorted(self.requests.items()):
                lines.append(f'payment_http_requests_total{{endpoint="{endpoint}",status="{status}"}} {count}')
            lines.append('# TYPE payment_http_duration_seconds summary')
            for endpoint, (count, total, maximum) in sorted(self.latency.items()):
                label = '{endpoint="' + endpoint + '"}'
                lines.extend([f'payment_http_duration_seconds_count{label} {count}',
                              f'payment_http_duration_seconds_sum{label} {total}',
                              f'payment_http_duration_seconds_max{label} {maximum}'])
        return lines


def snapshot(database):
    with database.connect() as conn:
        work = conn.execute('''SELECT kind,state,count(*) AS count,
            COALESCE(sum(failures),0) AS failures,
            COALESCE(sum(attempts),0) AS executions,
            COALESCE(max(EXTRACT(EPOCH FROM clock_timestamp()-updated_at)),0) AS oldest_update_seconds
            FROM wy_work WHERE state!='DONE' GROUP BY kind,state ORDER BY kind,state''').fetchall()
        pending = conn.execute('''SELECT count(*) AS count,
            COALESCE(max(EXTRACT(EPOCH FROM clock_timestamp()-created_at)),0) AS oldest_seconds
            FROM wy_payments WHERE attempt_status='pending' ''').fetchone()
        worker = conn.execute('''SELECT EXTRACT(EPOCH FROM clock_timestamp()-last_seen) AS age_seconds
            FROM wy_worker_health WHERE id=1''').fetchone()
        expired_claims=conn.execute("SELECT count(*) AS n FROM wy_work WHERE state='IN_PROGRESS' AND lease_until<=clock_timestamp()").fetchone()['n']
    return {'work': work, 'pending': pending,
            'expired_claims':expired_claims,
            'worker_heartbeat_age_seconds': float(worker['age_seconds']) if worker else None}


def render_shared(data):
    lines = ['# TYPE payment_work_items gauge']
    for row in data['work']:
        labels = '{kind="' + row['kind'] + '",state="' + row['state'] + '"}'
        lines.extend([f'payment_work_items{labels} {row["count"]}',
                      f'payment_work_failures{labels} {row["failures"]}',
                      f'payment_work_executions{labels} {row["executions"]}',
                      f'payment_work_oldest_update_seconds{labels} {row["oldest_update_seconds"]}'])
    lines.extend([f'payment_pending_attempts {data["pending"]["count"]}',
                  f'payment_oldest_pending_seconds {data["pending"]["oldest_seconds"]}',
                  f'payment_expired_claims {data["expired_claims"]}',
                  f'payment_worker_heartbeat_present {int(data["worker_heartbeat_age_seconds"] is not None)}'])
    if data['worker_heartbeat_age_seconds'] is not None:
        lines.append(f'payment_worker_heartbeat_age_seconds {data["worker_heartbeat_age_seconds"]}')
    return lines
