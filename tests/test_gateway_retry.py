"""Lost upstream replies may replay only the existing idempotent registration."""
import importlib.util
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sys
import threading
import unittest
from unittest.mock import Mock,patch
import requests
from frontend import server as gateway
from frontend.access import derived

TOKEN='gateway-transport-test-token-'+'x'*40

class GatewayRecoveryTests(unittest.TestCase):
    def client(self):
        env=patch.dict(os.environ,{'PAYMENT_API_TOKEN':TOKEN,'FRONTEND_AUTH':'true'})
        env.start();self.addCleanup(env.stop)
        return gateway.create_app().test_client()

    def headers(self):return {'Authorization':'Bearer '+derived(TOKEN,'operator')}

    def test_lost_reply_after_real_registration_commit_does_not_duplicate_party(self):
        directory=Path(__file__).resolve().parents[1]/'src/services/waiting-room'
        sys.path.insert(0,str(directory))
        spec=importlib.util.spec_from_file_location('waiting_gateway_retry_fixture',directory/'app.py')
        waiting=importlib.util.module_from_spec(spec);spec.loader.exec_module(waiting)
        queue=waiting.MemoryStore();queue.open_sale();app=waiting.create_app(queue)
        payloads=[]
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def do_POST(self):
                payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                payloads.append(payload)
                with app.test_client() as c:reply=c.post('/submit',json=payload)
                if len(payloads)==1:
                    # Real MemoryStore registration committed; discard its reply.
                    self.close_connection=True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                self.send_response(reply.status_code)
                self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(reply.data)))
                self.send_header('Connection','close');self.end_headers()
                self.wfile.write(reply.data);self.close_connection=True
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch.dict(gateway.SERVICES,{'waiting-room':'http://127.0.0.1:'+str(server.server_port)}):
                reply=self.client().post('/api/waiting-room/submit',json={
                    'user_id':'same-party','section':'D','party_size':2},headers=self.headers())
            self.assertEqual(reply.status_code,200)
            self.assertEqual(reply.headers['X-Gateway-Upstream-Attempts'],'2')
            self.assertEqual(len(payloads),2);self.assertEqual(payloads[0],payloads[1])
            state=queue.read()
            self.assertEqual(len(state['requests']),1)
            self.assertEqual(state['queue'],[reply.json['request_id']])
            self.assertEqual(reply.json['queue_number'],1);self.assertEqual(state['next_number'],2)
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_other_mutations_and_timeouts_are_not_replayed(self):
        client=self.client()
        for path,error in [('payment/payments',requests.ConnectionError('dropped')),
                           ('waiting-room/submit',requests.Timeout('timed out'))]:
            with self.subTest(path=path),patch('frontend.server.proxy_request',side_effect=error) as upstream:
                reply=client.post('/api/'+path,json={'user_id':'same-party'},headers=self.headers())
                self.assertEqual(reply.status_code,502);self.assertEqual(upstream.call_count,1)

    def test_application_rejections_are_not_retried(self):
        response=Mock(status_code=400,content=b'{"error":"invalid"}',headers={})
        with patch('frontend.server.proxy_request',return_value=response) as upstream:
            reply=self.client().post('/api/waiting-room/submit',json={'user_id':'same-party'},headers=self.headers())
            self.assertEqual(reply.status_code,400);self.assertEqual(upstream.call_count,1)
