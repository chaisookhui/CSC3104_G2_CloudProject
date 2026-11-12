"""Lab-only seat-store proxy: drop a committed reply or expose a crash checkpoint.

Never installed by the normal application launcher. Control paths are not routed
by the frontend. Test orchestration removes this proxy and restores worker URLs.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError

events={}
lock=threading.Lock()
released=threading.Event()

class Proxy(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        if self.path=='/fault/events':
            with lock: data=json.dumps(events).encode()
            self.send_response(200);self.end_headers();self.wfile.write(data)
        elif self.path=='/fault/release':
            released.set();self.send_response(200);self.end_headers()
        else: self.forward()
    def do_POST(self): self.forward()
    def forward(self):
        body=self.rfile.read(int(self.headers.get('Content-Length','0')))
        req=Request(os.environ['UPSTREAM']+self.path,data=body if self.command=='POST' else None,
                    headers={'Content-Type':'application/json'},method=self.command)
        try:
            with urlopen(req,timeout=10) as response: status,data=response.status,response.read()
        except HTTPError as error: status,data=error.code,error.read()
        except OSError:
            self.send_response(502);self.end_headers();return
        if self.path=='/seats/hold' and status==200:
            result=json.loads(data)
            if result.get('success'):
                rid=result['request_id']
                with lock:
                    first=rid not in events
                    events.setdefault(rid,dict(hold_id=result['hold_id'],hold_expiry=result['hold_expiry'],replies_dropped=0))
                    block=os.environ.get('FAULT_MODE')=='checkpoint' and not released.is_set()
                    drop=first or block
                    if drop: events[rid]['replies_dropped']+=1
                if block: released.wait(120)
                if drop:
                    self.close_connection=True
                    try:self.connection.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
                    self.connection.close();return
        self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)

if __name__=='__main__': ThreadingHTTPServer(('0.0.0.0',5003),Proxy).serve_forever()
