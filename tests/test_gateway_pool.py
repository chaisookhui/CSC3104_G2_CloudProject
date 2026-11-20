"""Pooled upstream connections must not carry cookies between customers."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from frontend.http_client import proxy_request


class GatewayPoolTests(unittest.TestCase):
    def test_reuses_connection_without_reusing_upstream_cookies(self):
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            protocol_version='HTTP/1.1'
            def do_GET(self):
                seen.append((self.client_address,self.headers.get('Cookie')))
                self.send_response(200)
                self.send_header('Content-Length','2')
                self.send_header('Set-Cookie','upstream_identity=first-customer')
                self.end_headers();self.wfile.write(b'{}')
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url='http://127.0.0.1:'+str(server.server_port)
            # A dedicated thread simulates one long-lived Waitress worker.
            def work():
                for _ in range(2):
                    self.assertEqual(proxy_request('GET',url,timeout=2).status_code,200)
            with ThreadPoolExecutor(max_workers=1) as pool:pool.submit(work).result()
            self.assertEqual(len(seen),2)
            self.assertEqual(seen[0][0],seen[1][0])
            self.assertEqual([p[1] for p in seen],[None,None])
        finally:
            server.shutdown();server.server_close();thread.join()
