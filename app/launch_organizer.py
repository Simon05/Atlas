#!/usr/bin/env python3
"""Serve Atlas on loopback, with authenticated verification and confirmed batches."""
import json,mimetypes,re,secrets,webbrowser,argparse
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
from atlas_execution import Execution
from atlas_sources import Sources
HERE=Path(__file__).resolve().parent
class Handler(BaseHTTPRequestHandler):
 def hosts(self):return {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
 def allowed_host(self):return self.headers.get('Host') in self.hosts()
 def origin_ok(self):return self.headers.get('Origin') in {'http://'+h for h in self.hosts()} and self.headers.get('Sec-Fetch-Site') not in {'cross-site'}
 def context(self):
  query=parse_qs(urlparse(self.path).query);ident=query.get('source',[self.headers.get('X-Atlas-Source','downloads')])[0]
  return self.server.sources.get(ident)
 def token_ok(self):
  try:return secrets.compare_digest(self.headers.get('X-Atlas-Token',''),self.context()['service'].token)
  except ValueError:return False
 def security(self):
  self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.send_header('Content-Security-Policy',"default-src 'self' blob: data:; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
 def respond(self,data,status=200,kind='application/json'):
  raw=json.dumps(data,ensure_ascii=False).encode() if kind=='application/json' else data.encode();self.send_response(status);self.security();self.send_header('Content-Type',kind+'; charset=utf-8');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_OPTIONS(self):self.send_error(403,'Cross-origin requests are not allowed')
 def do_POST(self):
  if not self.allowed_host() or not self.origin_ok() or not self.token_ok():self.respond({'error':'This request did not come from this Atlas session. Reload Atlas and try again.'},403);return
  if self.headers.get('Content-Type','').split(';')[0]!='application/json':self.respond({'error':'JSON required'},415);return
  try:
   n=int(self.headers.get('Content-Length','0'))
   if not 0<n<=16*1024*1024:raise ValueError('Invalid request size.')
   body=json.loads(self.rfile.read(n))
   if not isinstance(body,dict):raise ValueError('JSON object required.')
   route=urlparse(self.path).path;service=self.context()['service']
   if route=='/api/choose-source':self.respond(self.server.sources.choose());return
   if route=='/api/scan-source':self.respond(self.server.sources.start(body.get('path')));return
   if route=='/api/cancel-scan':self.respond(self.server.sources.stop(body.get('id')));return
   if route=='/api/reveal':self.respond(service.reveal(body.get('path')));return
   if route=='/api/choose-destination':self.respond(service.choose_destination());return
   if route=='/api/verify':result=service.verify(body.get('plan'),body.get('allowProjects') is True)
   elif route in ('/api/apply','/api/undo'):
    mode='apply' if route.endswith('/apply') else 'undo'
    if body.get('confirmation')!=('APPLY' if mode=='apply' else 'RESTORE'):raise ValueError('Review and explicitly confirm these actions first.')
    result=service.operate(body.get('jobId'),mode,body.get('reviewToken'),body.get('scope','all'))
   else:self.respond({'error':'Unknown action'},404);return
   self.respond({'job':result})
  except (ValueError,TypeError,KeyError,OSError) as e:self.respond({'error':str(e)},400)
 def do_GET(self):
  if not self.allowed_host():self.send_error(403);return
  route=urlparse(self.path)
  try:context=self.context();service=context['service']
  except ValueError as e:self.respond({'error':str(e)},404);return
  if route.path=='/api/session':
   if self.headers.get('Sec-Fetch-Site')=='cross-site':self.send_error(403);return
   self.respond({'token':service.token,**service.snapshot(),'sourceId':context['id'],**self.server.sources.snapshot()});return
  if route.path.startswith('/api/'):
   if not self.token_ok():self.send_error(403);return
   if route.path=='/api/state':self.respond(service.snapshot());return
   if route.path=='/api/sources':self.respond(self.server.sources.snapshot());return
   if route.path=='/api/journal':
    ident=parse_qs(route.query).get('id',[''])[0];job=service.jobs.get(ident)
    if not job:self.respond({'error':'Unknown run'},404);return
    file=service._folder(ident)/'undo-log.jsonl'
    if not file.exists():self.respond({'error':'No filesystem actions have been recorded yet.'},404);return
    self.respond(file.read_text(),kind='application/x-ndjson');return
   self.send_error(404);return
  if route.path in ('/','/index.html'):
   path=context['here']/'Downloads Organizer.html'
   with self.server.sources.lock:
    for job in self.server.sources.scans.values():
     if job['sourceId']==context['id'] and job['state']=='ready':job['state']='opened'
  elif route.path=='/media':
   key=parse_qs(route.query).get('path',[''])[0]
   if key not in {r['path'] for r in context['manifest']['records'] if r['kind']=='file'}:self.send_error(404);return
   path=Path(context['manifest']['root'])/key
   if any(p.is_symlink() for p in [path,*path.parents]) or not path.is_file():self.send_error(403);return
  else:self.send_error(404);return
  try:
   size=path.stat().st_size;start,end=0,size-1;partial=False
   if self.headers.get('Range'):
    match=re.fullmatch(r'bytes=(\d+)-(\d*)',self.headers['Range'])
    if not match:self.send_error(416);return
    start=int(match[1]);end=min(int(match[2]) if match[2] else size-1,size-1);partial=True
    if start>end:self.send_error(416);return
   self.send_response(206 if partial else 200);self.security()
   if route.path=='/media':self.send_header('Content-Security-Policy',"sandbox; default-src 'none'; style-src 'unsafe-inline'")
   self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'application/octet-stream');self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
   if partial:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
   self.end_headers()
   with path.open('rb') as f:
    f.seek(start);remaining=end-start+1
    while remaining:
     chunk=f.read(min(1024*1024,remaining))
     if not chunk:break
     self.wfile.write(chunk);remaining-=len(chunk)
  except (BrokenPipeError,ConnectionResetError):pass
  except OSError:self.send_error(404)
 def log_message(self,*args):pass

def make_server(port=8765,manifest=None,here=HERE,execution=None,app_dir=None):
 manifest=manifest or json.loads((Path(here)/'scan.json').read_text());server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.execution=execution or Execution(manifest,here,engine_path=Path(app_dir)/'apply_plan.py' if app_dir else None);server.sources=Sources(manifest,here,server.execution,app_dir=app_dir);server.root=Path(manifest['root']);server.allowed={r['path'] for r in manifest['records'] if r['kind']=='file'};return server
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8765);parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
 server=make_server(args.port);url=f'http://127.0.0.1:{server.server_port}';print('Downloads Atlas:',url,flush=True)
 if not args.no_browser:webbrowser.open(url)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close()
