"""Independent local sources and read-only background scans for Atlas."""
import hashlib,json,os,subprocess,sys,threading,time,uuid
from pathlib import Path
from atlas_execution import Execution
from apply_plan import no_links
from atlas_scan import scan
from atlas_relations import build_relations
class Sources:
 def __init__(self,manifest,here,execution=None,app_dir=None):
  self.here=Path(here).resolve();self.app_dir=Path(app_dir).resolve() if app_dir else self.here;self.folder=self.here/'sources';self.lock=threading.RLock();self.scans={};self.contexts={};self.cancel=threading.Event()
  no_links(self.folder)
  service=execution or Execution(manifest,here)
  self.contexts['downloads']={'manifest':manifest,'service':service,'here':self.here,'name':Path(manifest['root']).name,'id':'downloads'}
  if self.folder.exists():
   for p in self.folder.glob('*/scan.json'):
    try:
     ident=p.parent.name
     if len(ident)!=20 or any(c not in '0123456789abcdef' for c in ident) or p.is_symlink():continue
     no_links(p);d=json.loads(p.read_text());self.contexts[ident]={'manifest':d,'service':Execution(d,p.parent,engine_path=self.app_dir/'apply_plan.py'),'here':p.parent,'name':Path(d['root']).name,'id':ident}
    except (ValueError,OSError,KeyError):continue
 def get(self,ident):
  with self.lock:
   if ident not in self.contexts:raise ValueError('Unknown folder. Return to Atlas and choose a scanned folder.')
   return self.contexts[ident]
 def snapshot(self):
  with self.lock:
   return {'sources':[{'id':c['id'],'name':c['name'],'root':c['manifest']['root'],'scannedAt':c['manifest']['scannedAt'],'units':len(c['manifest']['units'])} for c in self.contexts.values() if not c['manifest'].get('bootstrap')],'scans':[dict(j) for j in self.scans.values()]}
 def choose(self):
  if sys.platform!='darwin':raise ValueError('Enter an absolute folder path instead.')
  try:r=subprocess.run(['/usr/bin/osascript','-e','POSIX path of (choose folder with prompt "Choose a folder for Atlas to scan. Your files stay in place." default location (path to documents folder))'],capture_output=True,text=True,timeout=120)
  except subprocess.TimeoutExpired:raise ValueError('The folder chooser timed out. Try again.')
  if r.returncode:
   if '-128' in r.stderr:return {'cancelled':True}
   raise ValueError('Finder could not open the folder chooser. Enter the folder path instead.')
  return {'path':str(self.validate(r.stdout.strip()))}
 def validate(self,value):
  if not isinstance(value,str) or not Path(value).is_absolute() or '\x00' in value or '..' in Path(value).parts:raise ValueError('Choose an absolute folder path.')
  p=Path(value)
  if any(q.is_symlink() for q in [p,*p.parents]):raise ValueError('Choose the original folder rather than a symbolic link.')
  p=p.resolve()
  if not p.is_dir():raise ValueError('This folder is unavailable. Check its path and access permissions.')
  if p==Path.home() or p in Path.home().parents or any(p==Path(n) or Path(n) in p.parents for n in ('/System','/Library','/Applications','/private','/dev','/proc','/Volumes')):raise ValueError('Choose a personal folder such as Documents or a project collection. System folders and the entire home folder are not scanned.')
  if p==self.here or self.here in p.parents or (self.app_dir!=self.here and (p==self.app_dir.parent or self.app_dir in p.parents)):raise ValueError('Choose your files folder, outside the Atlas application folder.')
  return p
 def start(self,value):
  root=self.validate(value)
  with self.lock:
   for c in self.contexts.values():
    if c['manifest'].get('bootstrap'):continue
    old=Path(c['manifest']['root'])
    if root==old:return {'existing':c['id']}
    if root in old.parents or old in root.parents:
     # Parent and child sources could mutate the same intact units under different plans.
     if c['id']!='downloads':raise ValueError('This overlaps another scanned folder. Open that folder instead, or choose a separate folder to keep plans independent.')
     if old in root.parents:raise ValueError('This is already inside Downloads. Use its existing plan to keep folder units intact.')
   if any(j['state']=='scanning' for j in self.scans.values()):raise ValueError('One scan is already running. Let it finish or cancel it first.')
   ident=hashlib.sha256(str(root).encode()).hexdigest()[:20];job={'id':uuid.uuid4().hex,'sourceId':ident,'root':str(root),'state':'scanning','phase':'inventory','message':'Starting a read-only scan…','completed':0,'total':0,'startedAt':time.time()};self.scans[job['id']]=job;self.cancel.clear()
  def progress(**fields):
   with self.lock:job.update(fields)
  def worker():
   folder=self.folder/ident
   try:
    # Exclude the running Atlas workspace when scanning a parent like Documents.
    d=scan(root,progress,self.cancel.is_set,exclude=[self.here.parent]);d['sourceId']=ident
    try:
     from atlas_previews import previews
     thumbs=previews(d,progress,self.cancel.is_set)
    except ImportError:thumbs={};d['limitations'].append('Image preview library unavailable; original-file previews remain available.')
    if self.cancel.is_set():raise ValueError('Scan cancelled. No files were changed.')
    no_links(folder);folder.mkdir(parents=True,exist_ok=True);os.chmod(folder,0o700)
    progress(phase='connections',message='Explaining project links and content matches…',completed=0,total=0)
    evidence=build_relations(d);(folder/'connections.json').write_text(json.dumps(evidence,ensure_ascii=False,separators=(',',':')))
    template=(self.app_dir/'atlas-template.html').read_text();safe=lambda v:json.dumps(v,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    (folder/'Downloads Organizer.html').write_text(template.replace('__SNAPSHOT__',safe(d)).replace('__THUMBNAILS__',safe(thumbs)).replace('__CONNECTION_DATA__',safe(evidence)))
    # Publishing scan.json last makes only complete snapshots discoverable after restart.
    temp=folder/'scan.tmp';temp.write_text(json.dumps(d,ensure_ascii=False,separators=(',',':')));os.replace(temp,folder/'scan.json')
    context={'manifest':d,'service':Execution(d,folder,engine_path=self.app_dir/'apply_plan.py'),'here':folder,'name':root.name,'id':ident}
    with self.lock:self.contexts[ident]=context;job.update(state='ready',phase='complete',message='Your map is ready.',completed=len(d['units']),total=len(d['units']))
   except Exception as e:
    with self.lock:job.update(state='cancelled' if self.cancel.is_set() else 'failed',message=str(e))
  threading.Thread(target=worker,daemon=True).start();return {'scan':dict(job)}
 def stop(self,ident):
  with self.lock:
   if ident not in self.scans:raise ValueError('Unknown scan.')
   if self.scans[ident]['state']=='scanning':self.cancel.set();self.scans[ident]['message']='Stopping the scan. Your files are unchanged…'
  return self.snapshot()
