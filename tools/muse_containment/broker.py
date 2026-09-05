"""Campaign-only credential broker and synthetic upstream. Never log body/auth values."""
import argparse
import http.client
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MODEL = 'muse-spark-1.3-contributor'
args = None
authorization = None
lock = threading.Lock()
counts = {'requests': 0, 'authenticated_upstream': 0}

def log(**facts):
    print(json.dumps(facts, sort_keys=True), flush=True)

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'
    def log_message(self, *values): pass
    def reply(self, status, data):
        data = json.dumps(data).encode()
        self.send_response(status); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_GET(self): self.handle_request()
    def do_POST(self): self.handle_request()
    def handle_request(self):
        global authorization
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 20_000_000: return self.reply(413, {'error':'request_size'})
            body = self.rfile.read(length)
            path = urlsplit(self.path).path
            if path.startswith('/muse-code/'):
                path = '/v1' + path
            if path == '/health': return self.reply(200, {'ready': True, 'credential_loaded': bool(authorization), 'mode': args.mode})
            if args.mode == 'fixture': return self.fixture(path, body)
            bootstrap = path.startswith('/bootstrap/' + args.bootstrap + '/') if args.bootstrap else False
            if bootstrap:
                path = path[len('/bootstrap/' + args.bootstrap):]
            if path not in ('/v1/responses', '/v1/muse-code/models', '/v1/models', '/v1/muse-code/config'):
                log(kind='route_denied'); return self.reply(403, {'error':'route_not_allowed'})
            if path.endswith('/responses'):
                if self.command != 'POST': return self.reply(405, {'error':'method_not_allowed'})
                request = json.loads(body)
                if request.get('model') != MODEL: return self.reply(403, {'error':'model_not_allowed'})
            elif self.command != 'GET': return self.reply(405, {'error':'method_not_allowed'})
            # Catalog/config are public frozen startup facts; no account data is forwarded.
            if path.endswith('/models'):
                return self.reply(200, {'data':[{'id':MODEL,'object':'model','owned_by':'meta'}], 'models':[{'id':MODEL,'model_id':MODEL,'display_name':MODEL,'display_label':MODEL,'context_limit':1007997,'output_limit':128000}], 'default_model':MODEL})
            if path.endswith('/config'): return self.reply(200, {})
            if not bootstrap and not secrets.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + args.worker_token):
                return self.reply(401, {'error':'worker_capability_required'})
            if bootstrap:
                header = self.headers.get('Authorization', '')
                if not header.startswith('Bearer ') or len(header) < 15: return self.reply(401, {'error':'bootstrap_auth_missing'})
                with lock:
                    if authorization is not None: return self.reply(409, {'error':'bootstrap_already_used'})
                    authorization = header
                    args.bootstrap = ''
                log(kind='bootstrap_consumed')
            if not authorization: return self.reply(503, {'error':'credential_not_loaded'})
            upstream = urlsplit(args.upstream)
            cls = http.client.HTTPSConnection if upstream.scheme == 'https' else http.client.HTTPConnection
            conn = cls(upstream.hostname, upstream.port, timeout=120)
            headers = {'Authorization': authorization, 'Content-Type':'application/json', 'Accept':'text/event-stream', 'User-Agent':self.headers.get('User-Agent','capy-campaign-broker')}
            conn.request(self.command, upstream.path.rstrip('/') + path[len('/v1'):], body=body, headers=headers)
            response = conn.getresponse()
            with lock: counts['requests'] += 1
            log(kind='forward', status=response.status, bootstrap=bootstrap, model=MODEL, request_bytes=len(body))
            self.send_response(response.status);self.send_header('Content-Type',response.getheader('Content-Type','application/json'));self.send_header('Connection','close');self.end_headers()
            try:
                while chunk := response.read1(65536): self.wfile.write(chunk);self.wfile.flush()
            finally:conn.close()
        except (OSError, ValueError, http.client.HTTPException) as exc:
            log(kind='error', error=type(exc).__name__)
            try:self.reply(502, {'error':type(exc).__name__})
            except OSError:pass
    def fixture(self, path, body):
        expected = 'Bearer ' + os.environ.get('MUSE_SECRET_CANARY','')
        if self.headers.get('Authorization') != expected: return self.reply(401, {'error':'synthetic_auth_rejected'})
        if path != '/v1/responses': return self.reply(404, {'error':'fixture_route'})
        req=json.loads(body)
        with lock: counts['authenticated_upstream']+=1
        tools=req.get('tools',[])
        log(kind='synthetic_tool_groups', names=[t.get('name') for t in tools])
        flat=[]
        for top in tools:
            if top.get('type')=='namespace':
                flat.extend(dict(t, namespace=top['name']) for t in top.get('tools',[]))
            else: flat.append(top)
        tools=flat
        names=[t.get('name') or t.get('function',{}).get('name') for t in tools]
        log(kind='synthetic_upstream_authenticated', count=counts['authenticated_upstream'], requested_model=req.get('model'), tool_names=names)
        have_result=any(v.get('type')=='function_call_output' for v in req.get('input',[]) if isinstance(v,dict))
        if not have_result:
            chosen=next((t for t in tools if (t.get('name') or t.get('function',{}).get('name')) in ('bash','shell','exec_command')),None)
            if chosen is None:return self.reply(400,{'error':'fixture_shell_tool_unavailable'})
            tool=chosen.get('function',chosen);schema=tool.get('parameters',{})
            log(kind='synthetic_tool_schema', name=tool['name'], parameters=schema)
            values={}
            for key,prop in schema.get('properties',{}).items():
                if key in ('command','cmd'):values[key]='python3 /workspace/tools/muse_containment/probe.py'
                elif key in ('description','title'):values[key]='Run synthetic containment matrix'
                elif key in schema.get('required',[]):
                    if key in ('timeout_ms','timeout'):values[key]=10000
                    elif prop.get('type')=='boolean':values[key]=False
                    elif prop.get('type')=='integer':values[key]=1
                    elif prop.get('type')=='string':values[key]=''
            item={'type':'function_call','id':'fc_capy_fixture','call_id':'call_capy_fixture','name':tool['name'],'arguments':json.dumps(values)}
            if 'namespace' in chosen: item['namespace']=chosen['namespace']
        else:
            item={'type':'message','id':'msg_capy_fixture','role':'assistant','status':'completed','content':[{'type':'output_text','text':'CAPY_SYNTHETIC_TRANSPORT_FINISHED. This was a fixture, not a model evaluation.','annotations':[]}]}
        response={'id':'resp_capy_fixture_'+secrets.token_hex(6),'object':'response','created_at':0,'status':'completed','model':'capy.synthetic-containment-fixture','output':[item],'usage':{'input_tokens':0,'output_tokens':0,'total_tokens':0}}
        self.send_response(200);self.send_header('Content-Type','text/event-stream');self.end_headers()
        events=[('response.created',{'response':dict(response,status='in_progress',output=[])}),('response.output_item.added',{'output_index':0,'item':dict(item,arguments='') if item['type']=='function_call' else item})]
        if item['type']=='function_call':
            events += [('response.function_call_arguments.delta',{'item_id':item['id'],'output_index':0,'delta':item['arguments']}),('response.function_call_arguments.done',{'item_id':item['id'],'output_index':0,'arguments':item['arguments']})]
        else:
            events += [('response.output_text.delta',{'item_id':item['id'],'output_index':0,'content_index':0,'delta':item['content'][0]['text']})]
        events += [('response.output_item.done',{'output_index':0,'item':item}),('response.completed',{'response':response})]
        for i,(kind,data) in enumerate(events):
            wire={'type':kind,'sequence_number':i,**data};self.wfile.write(('event: '+kind+'\ndata: '+json.dumps(wire)+'\n\n').encode());self.wfile.flush()

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=['fixture','gateway'],required=True);parser.add_argument('--port',type=int,default=8765);parser.add_argument('--upstream',default='https://api.meta.ai/v1');parser.add_argument('--bootstrap',default='');parser.add_argument('--worker-token', default='');args=parser.parse_args()
    if args.mode == 'gateway' and len(args.worker_token) < 32:
        parser.error('gateway requires a random worker capability of at least 32 characters')
    if args.mode=='gateway' and args.upstream.startswith('http://fixture:') and not args.bootstrap:
        authorization='Bearer '+os.environ['MUSE_SECRET_CANARY']
    log(kind='started',mode=args.mode,credential_loaded=bool(authorization))
    ThreadingHTTPServer(('0.0.0.0',args.port),Handler).serve_forever()
