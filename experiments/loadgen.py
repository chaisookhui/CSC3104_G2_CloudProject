"""Open-loop HTTP arrivals. Scheduling never waits for an earlier response.

Launch time is aiohttp's headers-send callback after connection acquisition,
not task enqueue time or server receipt. No submission retries: ambiguous
replies are reconciled by the caller.
"""
import asyncio
import json
import random
import time

from runtime import request_headers, utc


def check_runtime():
    try:
        import aiohttp
    except ImportError as error:
        raise RuntimeError('Install load dependencies first: python -m pip install -r experiments/requirements-load.txt') from error
    return aiohttp.__version__


async def arrivals(base, schedule, identity, rows, capacity=4096, timeout=15):
    preparing = time.perf_counter()
    preparing_cpu = time.process_time()
    check_runtime()
    import aiohttp
    if capacity < 1:
        raise ValueError('capacity must be positive')
    rng = random.Random(42)
    trace = aiohttp.TraceConfig()
    peak = 0
    pending = set()

    async def launched(session, context, params):
        row = context.trace_request_ctx
        row.setdefault('launched_seconds', time.perf_counter() - started)
        row.setdefault('sent_at', utc())

    trace.on_request_headers_sent.append(launched)

    async def send(session, row):
        begin = time.perf_counter()
        row['dispatch_seconds'] = begin - started
        try:
            async with session.post(base.rstrip('/') + '/api/waiting-room/submit',
                                    json=row['payload'], trace_request_ctx=row,
                                    allow_redirects=False) as response:
                raw = await response.text()
                try:
                    data = json.loads(raw)
                except ValueError:
                    data = raw
                row['response'] = dict(status=response.status, data=data,
                    instance=response.headers.get('X-Service-Instance'),
                    upstream_attempts=int(response.headers['X-Gateway-Upstream-Attempts'])
                        if 'X-Gateway-Upstream-Attempts' in response.headers else None,
                    elapsed_ms=(time.perf_counter()-begin)*1000)
                row['outcome'] = ('ACCEPTED' if response.status in (200, 201)
                    and isinstance(data, dict) and data.get('request_id') else
                    'REJECTED' if 400 <= response.status < 500 else 'UNKNOWN')
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as error:
            row['response'] = dict(status=0, data=None, error=type(error).__name__,
                error_message=str(error),os_errno=getattr(error,'errno',None),
                timed_out=isinstance(error, asyncio.TimeoutError),
                elapsed_ms=(time.perf_counter()-begin)*1000)
            row['outcome'] = 'TIMED_OUT' if isinstance(error, asyncio.TimeoutError) else 'UNKNOWN'
        row['completed_seconds'] = time.perf_counter() - started

    connector = aiohttp.TCPConnector(limit=capacity, limit_per_host=capacity)
    headers_started = time.perf_counter()
    headers = request_headers()
    headers_seconds = time.perf_counter()-headers_started
    session_started = time.perf_counter()
    async with aiohttp.ClientSession(connector=connector, headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout), trace_configs=[trace],
            cookie_jar=aiohttp.DummyCookieJar(), trust_env=False) as session:
        # Prepare configuration and the pool before the offered-arrival epoch.
        # No connection or request is warmed up here: connection acquisition and
        # every runtime stall remain part of each request's measured launch lag.
        arrival_started_at = utc()
        started = time.perf_counter()
        cpu = time.process_time()
        preparation_seconds = started-preparing
        preparation_cpu_seconds = cpu-preparing_cpu
        session_seconds = started-session_started
        try:
            for index, (scheduled, phase) in enumerate(schedule):
                await asyncio.sleep(max(0, started+scheduled-time.perf_counter()))
                for task in pending:
                    if task.done(): task.result()
                pending = {task for task in pending if not task.done()}
                row = dict(index=index, scheduled_seconds=scheduled, phase=phase,
                    payload=dict(user_id=f'{identity}-{index}', section=rng.choice('ABCD'),
                                 party_size=rng.randint(1, 4)), outcome='DROPPED_GENERATOR')
                rows.append(row)
                if len(pending) < capacity:
                    pending.add(asyncio.create_task(send(session, row)))
                    peak = max(peak, len(pending))
                else:
                    row['drop_reason']='concurrency_capacity_exhausted'
            await asyncio.gather(*pending)
        finally:
            # Do not leave active requests after an interrupted run.
            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
    return dict(elapsed=time.perf_counter()-started, cpu_seconds=time.process_time()-cpu,
                arrival_started_at=arrival_started_at,preparation_seconds=preparation_seconds,
                preparation_cpu_seconds=preparation_cpu_seconds,
                preparation_phases_seconds=dict(headers=headers_seconds,session=session_seconds,
                    other=max(0,preparation_seconds-headers_seconds-session_seconds)),
                peak_in_flight=peak, capacity=capacity, engine='aiohttp', version=aiohttp.__version__,
                clock=time.get_clock_info('perf_counter').implementation,
                clock_resolution_seconds=time.get_clock_info('perf_counter').resolution,
                peak_definition='Outstanding client tasks, including connecting; not database transaction concurrency.')


def generate(base, schedule, identity, rows, capacity=4096):
    return asyncio.run(arrivals(base, schedule, identity, rows, capacity))
