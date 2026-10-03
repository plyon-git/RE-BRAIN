"""Standalone local ML/NLP microservice, compatible with the BRAIN API."""
import argparse
import hmac
import ipaddress
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from engine import KnowledgeIndex, OpportunityModel, extract

BASE = Path(__file__).resolve().parents[2]
INDEX = KnowledgeIndex(os.getenv('BRAIN_VAULT', str(BASE/'knowledge'/'obsidian')))
MODEL = OpportunityModel(os.getenv('BRAIN_MODEL', str(BASE/'runtime'/'model.json')))

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def reply(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == '/health':
            self.reply(200, {'status':'ok','engine':'local','documents':len(INDEX.documents)})
        elif not self.authorized():
            self.reply(401,{'error':'Bearer authentication required'})
        elif self.path == '/models':
            self.reply(200,MODEL.status())
        else:
            self.reply(404,{'error':'Not found'})

    def authorized(self):
        key = os.getenv('BRAIN_API_KEY','')
        if key:
            return hmac.compare_digest(self.headers.get('Authorization',''), 'Bearer '+key)
        try:
            return ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            return False

    def do_POST(self):
        if not self.authorized():
            return self.reply(401,{'error':'Bearer authentication required'})
        try:
            size = int(self.headers.get('Content-Length','0'))
            if not 0<size<=16_000_000:
                return self.reply(413,{'error':'JSON body must be below 16 MB'})
            body = json.loads(self.rfile.read(size))
            if not isinstance(body,dict):
                raise ValueError('JSON body must be an object')
            if self.path == '/search':
                result = INDEX.search(body.get('query',''),body.get('limit',10))
            elif self.path == '/predict':
                result = MODEL.predict(body.get('features',{}))
            elif self.path == '/train':
                result = MODEL.train(body.get('rows',[]),synthetic=body.get('synthetic',False))
            elif self.path == '/reference':
                result = MODEL.train_reference()
            elif self.path == '/reindex':
                result = INDEX.build()
            elif self.path == '/extract':
                result = extract(body.get('text',''))
            else:
                return self.reply(404,{'error':'Not found'})
            self.reply(200,result)
        except (ValueError,TypeError,KeyError) as exc:
            self.reply(400,{'error':str(exc)})
        except (BrokenPipeError,ConnectionResetError):
            pass
        except OSError:
            self.reply(503,{'error':'Local model or vault storage is unavailable'})

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host',default=os.getenv('BRAIN_INTELLIGENCE_HOST','127.0.0.1'))
    parser.add_argument('--port',type=int,default=int(os.getenv('BRAIN_INTELLIGENCE_PORT','8083')))
    parser.add_argument('--reference',action='store_true')
    args = parser.parse_args()
    if args.reference and not MODEL.model:
        MODEL.train_reference()
    print(f'101XVC BRAIN intelligence on {args.host}:{args.port}',flush=True)
    ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
