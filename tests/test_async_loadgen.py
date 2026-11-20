"""Exercise real sockets, delay, rejections and pool exhaustion."""
import asyncio
from pathlib import Path
import sys
import time
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments'))
import control
from loadgen import arrivals


class AsyncArrivalsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiohttp import web
        self.web = web
        self.seen = []
        self.code = 201
        self.delay = .08
        self.gate = None
        async def submit(request):
            data = await request.json()
            self.seen.append(data['user_id'])
            if self.gate is not None:
                await self.gate.wait()
            await asyncio.sleep(self.delay)
            return web.json_response({'request_id': data['user_id']}, status=self.code,
                                     headers={'X-Service-Instance': 'stub'})
        app = web.Application()
        app.router.add_post('/api/waiting-room/submit', submit)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, '127.0.0.1', 0)
        await site.start()
        self.base = 'http://127.0.0.1:'+str(site._server.sockets[0].getsockname()[1])

    async def asyncTearDown(self):
        await self.runner.cleanup()

    async def test_delayed_responses_do_not_serialize_arrivals(self):
        rows = []
        with patch('loadgen.request_headers', return_value={}):
            result = await arrivals(self.base, [(0, 'surge')]*40, 'identity', rows, capacity=64)
        self.assertEqual(len(set(self.seen)), 40)
        self.assertTrue(all(row['outcome']=='ACCEPTED' for row in rows))
        self.assertTrue(all('launched_seconds' in row for row in rows))
        self.assertGreater(result['peak_in_flight'], 1)
        self.assertEqual({r['response']['instance'] for r in rows}, {'stub'})

    async def test_slow_client_preparation_precedes_the_unchanged_arrival_schedule(self):
        rows=[]
        def headers():
            time.sleep(1.15)
            return {}
        schedule=[(0,'baseline'),(.2,'baseline'),(.4,'baseline')]
        with patch('loadgen.request_headers',side_effect=headers):
            result=await arrivals(self.base,schedule,'preparation',rows)
        self.assertEqual([r['scheduled_seconds'] for r in rows],[0,.2,.4])
        self.assertEqual(len(self.seen),3)
        self.assertTrue(all(r['outcome']=='ACCEPTED' for r in rows))
        self.assertLess(max(r['launched_seconds']-r['scheduled_seconds'] for r in rows),1)
        self.assertGreaterEqual(result['preparation_seconds'],1.15)

    async def test_stall_after_arrivals_begin_remains_measured_launch_lag(self):
        rows=[]
        async def stall():
            await asyncio.sleep(.05)
            time.sleep(1.15)
        task=asyncio.create_task(stall())
        with patch('loadgen.request_headers',return_value={}):
            await arrivals(self.base,[(0,'baseline'),(.2,'baseline'),(.4,'baseline')],
                'runtime-stall',rows)
        await task
        self.assertEqual(len(self.seen),3)
        self.assertGreater(max(r['launched_seconds']-r['scheduled_seconds'] for r in rows),1)

    async def test_capacity_exhaustion_is_explicit_and_not_retried(self):
        rows = []
        self.gate = asyncio.Event()
        async def release_after_scheduling():
            while len(rows)<40: await asyncio.sleep(0)
            self.gate.set()
        release=asyncio.create_task(release_after_scheduling())
        with patch('loadgen.request_headers', return_value={}):
            await arrivals(self.base, [(0, 'surge')]*40, 'identity', rows, capacity=1)
        await release
        self.assertEqual(len(self.seen), 1)
        self.assertEqual(sum(r['outcome']=='DROPPED_GENERATOR' for r in rows), 39)
        self.assertTrue(all('launched_seconds' not in r for r in rows if r['outcome']=='DROPPED_GENERATOR'))

    async def test_rejection_and_timeout_are_not_http_success(self):
        self.code = 429
        rows = []
        with patch('loadgen.request_headers', return_value={}):
            await arrivals(self.base, [(0, 'baseline')], 'reject', rows)
            self.delay = .2
            await arrivals(self.base, [(0, 'baseline')], 'timeout', rows, timeout=.01)
        self.assertEqual(rows[0]['outcome'], 'REJECTED')
        self.assertEqual(rows[1]['outcome'], 'TIMED_OUT')
        self.assertEqual(rows[1]['response']['status'], 0)

    async def test_immediate_pause_cancels_inflight_requests_and_stops_future_arrivals(self):
        rows=[];self.delay=.4
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{},clear=True),patch('loadgen.request_headers',return_value={}):
            session=control.Session(Path(folder),[],deployed=False,identity={})
            async def pause():
                while not self.seen:await asyncio.sleep(.005)
                control.atomic_json(session.request_path,dict(id='immediate-request',mode='immediate'))
            with self.assertRaises(control.Pause),session.activate():
                task=asyncio.create_task(pause())
                try:
                    await arrivals(self.base,[(0,'surge'),(2,'surge'),(3,'surge')],'pause',rows)
                finally:
                    await task
            self.assertEqual(len(self.seen),1)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['outcome'],'INTERRUPTED')
            self.assertEqual(control.read(session.path)['state'],'PAUSED')

    async def test_safe_pause_preserves_the_full_offer_schedule_and_response_drain(self):
        rows=[]
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{},clear=True),patch('loadgen.request_headers',return_value={}):
            session=control.Session(Path(folder),[],deployed=False,identity={})
            async def pause():
                await asyncio.sleep(.02)
                control.atomic_json(session.request_path,dict(id='safe-request',mode='safe'))
            with self.assertRaises(control.Pause),session.activate():
                with control.unit('trial',Path(folder)/'trial') as unit:
                    task=asyncio.create_task(pause())
                    result=await arrivals(self.base,[(0,'surge'),(.05,'surge'),(.1,'surge')],'safe',rows)
                    await task
                    control.atomic_json(unit.directory/'arrivals.json',rows)
                    unit.complete(result)
            self.assertEqual(len(self.seen),3)
            self.assertTrue(all(r['outcome']=='ACCEPTED' for r in rows))
            self.assertEqual(control.read(session.path)['units']['trial']['state'],'COMPLETE')


if __name__ == '__main__':
    unittest.main()
