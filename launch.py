#!/usr/bin/env python3
"""Start Atlas locally. Private scan data stays in .atlas/, outside source control."""
import argparse,json,sys,time,webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'app'))
from launch_organizer import make_server

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',type=int,default=8765);p.add_argument('--no-browser',action='store_true');p.add_argument('--data-dir',type=Path,default=ROOT/'.atlas');args=p.parse_args();data=args.data_dir.resolve();data.mkdir(parents=True,exist_ok=True)
 if (data/'scan.json').exists():manifest=json.loads((data/'scan.json').read_text())
 else:
  manifest=dict(version=1,bootstrap=True,root=str(Path.home()/'Downloads'),home=str(Path.home()),scannedAt=time.time(),units=[],records=[],duplicates=[],zipMatches=[],fontFamilies={},applications=[],errors=[],zipErrors=[],limitations=[])
  safe=lambda x:json.dumps(x).replace('<','\\u003c');page=(ROOT/'app'/'atlas-template.html').read_text().replace('__SNAPSHOT__',safe(manifest)).replace('__THUMBNAILS__','{}').replace('__CONNECTION_DATA__','null');(data/'Downloads Organizer.html').write_text(page)
 try:server=make_server(args.port,manifest,data,app_dir=ROOT/'app')
 except OSError as e:
  print('Atlas could not start:',e,'\nIf Atlas is already running, open http://127.0.0.1:'+str(args.port)+'. Or choose another --port.',file=sys.stderr);return 1
 url=f'http://127.0.0.1:{server.server_port}';print('Atlas:',url,flush=True)
 if not args.no_browser:webbrowser.open(url)
 try:server.serve_forever()
 except KeyboardInterrupt:pass
 finally:server.server_close()
 return 0
if __name__=='__main__':raise SystemExit(main())
