"""Authenticated loopback transport. This process never sends broker orders itself."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
from .models import ValidationError

MAX_BODY=2*1024*1024


def make_server(engine,port=None):
    token=engine.config.bridge_token
    if len(token)<32 or any(ord(c)<33 or ord(c)>126 for c in token):
        raise ValueError('BRIDGE_TOKEN must be at least 32 printable characters; run init first')

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(5)

        def log_message(self,*args):
            pass # Never log payloads, credentials or full network exceptions.

        def reply(self,status,body):
            encoded=body.encode()
            self.send_response(status)
            self.send_header('Content-Type','text/plain; charset=utf-8')
            self.send_header('Content-Length',str(len(encoded)))
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            if self.path=='/health': self.reply(200,'prediction-engine demo service')
            else: self.reply(404,'Not found')

        def do_POST(self):
            provided=self.headers.get('Authorization','')
            if not hmac.compare_digest(provided.encode(),('Bearer '+token).encode()):
                self.reply(401,'Unauthorized');return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=MAX_BODY:
                    self.reply(413,'Invalid body size');return
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    self.reply(415,'Use application/json');return
                body=self.rfile.read(length)
                if len(body)!=length: raise ValidationError('Incomplete request')
                def invalid_constant(_): raise ValidationError('Nonfinite JSON number')
                data=json.loads(body,parse_constant=invalid_constant)
                if not isinstance(data,dict): raise ValidationError('Expected JSON object')
                if self.path=='/v1/snapshot': result=engine.ingest(data)
                elif self.path=='/v1/result': engine.result(data);result='OK'
                elif self.path=='/v1/control':
                    if data.get('command') not in ('status','agents','positions','stats','pause','resume','help'):
                        raise ValidationError('Unknown control command')
                    result=engine.control(data['command'])
                else: self.reply(404,'Not found');return
                self.reply(200,result)
            except (ValueError,TypeError,UnicodeError):
                if self.path=='/v1/snapshot':
                    with engine.store.lock:
                        engine.snapshot=None
                        engine.last_issue='Invalid MT5 snapshot; entries blocked'
                self.reply(400,'Invalid request or command is currently blocked; inspect local status')
            except (BrokenPipeError,ConnectionResetError,TimeoutError):
                # Dispatch already journaled: a lost response is never reissued.
                pass
            except Exception:
                engine.pause()
                self.reply(500,'Internal error; engine paused. Inspect local journal.')

    server=ThreadingHTTPServer(('127.0.0.1',engine.config.port if port is None else port),Handler)
    server.daemon_threads=True
    server.service_actions=engine.monitor
    return server
