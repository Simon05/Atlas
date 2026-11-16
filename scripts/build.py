"""Build the small app template and refresh existing private snapshot pages."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];UI=ROOT/'ui';APP=ROOT/'app'
(ROOT/'work').mkdir(exist_ok=True)
s=(UI/'atlas.html').read_text()
for key,file in [('UX','atlas-ux'),('PLAN_FLOW','plan-flow'),('SOURCES','sources'),('CONNECTION','connections'),('CLEANUP','cleanup'),('OVERVIEW','overview'),('REFRESH','refresh')]:
 for kind,ext in [('STYLE','css'),('SCRIPT','js')]:s=s.replace('__'+key+'_'+kind+'__',(UI/(file+'.'+ext)).read_text())
s=s.replace('__SCAN_STATE_SCRIPT__',(UI/'scan-state.js').read_text())
(APP/'atlas-template.html').write_text(s)
(ROOT/'work'/'atlas.js').write_text("'use strict';\n"+s.split("<script>\n'use strict';")[1].split('</script>')[0])
def thumbs(path):
 token='<script id="thumbnails" type="application/json">';tail='';found=False
 with path.open() as f:
  while True:
   chunk=f.read(1024*1024)
   if not chunk:return '{}'
   text=tail+chunk
   if not found:
    i=text.find(token)
    if i<0:tail=text[-len(token):];continue
    text=text[i+len(token):];found=True
   if '</script>' in text:return text.split('</script>',1)[0]
   tail=text
safe=lambda x:x.replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
if '--template-only' not in sys.argv:
 for snap in (ROOT/'.atlas').rglob('scan.json'):
  html=snap.parent/'Downloads Organizer.html';t=thumbs(html) if html.exists() else '{}';e=snap.parent/'connections.json';page=s.replace('__THUMBNAILS__',t).replace('__CONNECTION_DATA__',safe(e.read_text()) if e.exists() else 'null');a,b=page.split('__SNAPSHOT__');tmp=html.with_suffix('.tmp')
  with tmp.open('w') as out:
   out.write(a)
   with snap.open() as f:
    for chunk in iter(lambda:f.read(1024*1024),''):out.write(safe(chunk))
   out.write(b)
  tmp.replace(html)
 print('Atlas is built. Run python3 launch.py')
