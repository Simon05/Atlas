"""Authenticated local execution service. All file mutations use apply_plan.py."""
import hashlib,json,os,secrets,subprocess,sys,threading,time,uuid
from pathlib import Path
import apply_plan as engine
BUSY={'verifying','applying','undoing'}
class Execution:
 def __init__(self,manifest,here,*,home=None,runner=None,engine_path=None):
  self.manifest=manifest;self.here=Path(here).resolve();self.home=Path(home) if home else Path.home();self.root=Path(manifest['root']);self.units={u['path']:u for u in manifest['units']};self.token=secrets.token_urlsafe(32);self.lock=threading.RLock();self.jobs={};self.runner=runner or self._subprocess;self.runs=self.here/'runs';self.engine_path=Path(engine_path) if engine_path else self.here/'apply_plan.py'
  engine.no_links(self.runs)
  if self.runs.exists():
   for p in self.runs.glob('*/job.json'):
    try:
     engine.no_links(p);job=json.loads(p.read_text());ident=job['id']
     if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident) or p.parent.name!=ident:continue
     if job['state'] in BUSY:job.update(state='failed',error='The local server restarted during this operation. Review the journal before restoring or verifying a new plan.')
     job['reviewToken']=secrets.token_urlsafe(24);self.jobs[ident]=job
    except (ValueError,OSError,KeyError):continue
 def _folder(self,ident):return self.runs/ident
 def _save(self,j):
  folder=self._folder(j['id']);engine.no_links(folder);folder.mkdir(parents=True,exist_ok=True);engine.no_links(folder/'job.json');tmp=folder/'job.tmp';engine.no_links(tmp);tmp.write_text(json.dumps(j,ensure_ascii=False));os.chmod(tmp,0o600);os.replace(tmp,folder/'job.json')
 def _events(self,j):
  p=self._folder(j['id'])/'undo-log.jsonl'
  if not p.exists():return []
  engine.no_links(p);events=[]
  for line in p.read_text().splitlines():
   try:events.append(json.loads(line))
   except ValueError:continue
  return events
 def _applied(self,j,events=None):
  events=self._events(j) if events is None else events;undone={e['id'] for e in events if e['event']=='undone'}
  intents={e['id']:e for e in events if e['event']=='intent'};done={e['id'] for e in events if e['event']=='done'}
  return [e for ident,e in intents.items() if ident not in undone and (ident in done or not Path(e['source']).exists() and Path(e['destination']).exists())]
 def applied_map(self,events_by_id=None):
  result={}
  for j in sorted(self.jobs.values(),key=lambda j:j['createdAt']):
   for e in self._applied(j,None if events_by_id is None else events_by_id[j['id']]):
    source=Path(e['source'])
    if source.parent==self.root:result[source.name]={'jobId':j['id'],'destination':e['destination'],'action':e['action']}
  return result
 def public(self,j,events=None,global_applied=None):
  events=self._events(j) if events is None else events;applied=self._applied(j,events);done={e['id'] for e in events if e['event']=='done'};undone={e['id'] for e in events if e['event']=='undone'};completed=[e for e in events if e['event']=='done'];sources={Path(e['source']).name for e in applied};actions=j['actions'];global_applied=self.applied_map() if global_applied is None else global_applied;external={a['source'] for a in actions if a['source'] in global_applied and global_applied[a['source']]['jobId']!=j['id']};pending=[a for a in actions if a['source'] not in sources and a['source'] not in external];restoring=bool(undone) or j['state'] in {'undoing','restore-paused','restored'}
  return {k:j.get(k) for k in ['id','state','createdAt','destinationRoot','error','output','verified','reviewToken']}|{'actions':actions,'appliedCount':len(applied),'total':len(actions),'nextBatch':pending if not restoring else [],'restoreBatch':[{'source':Path(e['source']).name,'action':e['action'],'destination':e['destination']} for e in reversed(applied)],'applied':list(sources),'completedElsewhere':len(external),'canApply':j['state'] in {'ready','paused'} and not restoring and bool(pending),'canUndo':bool(applied) and j['state'] not in BUSY,'journal':str(self._folder(j['id'])/'undo-log.jsonl'),'canInspectJournal':bool(events),'hasUndoHistory':restoring,'operationTotal':len(j.get('activeSources') or actions),'operationCompleted':sum((p not in sources if j['state'] in {'undoing','restore-paused','restored'} else p in global_applied) for p in (j.get('activeSources') or [a['source'] for a in actions])),'operationKind':j.get('activeScope','all')}
 def snapshot(self):
  with self.lock:
   events={j['id']:self._events(j) for j in self.jobs.values()};global_applied=self.applied_map(events)
   return {'protocolVersion':3,'connected':True,'busy':any(j['state'] in BUSY for j in self.jobs.values()),'jobs':[self.public(j,events[j['id']],global_applied) for j in sorted(self.jobs.values(),key=lambda j:j['createdAt'],reverse=True)],'applied':global_applied}

 def reveal_path(self,key):
  if not isinstance(key,str):raise ValueError('Choose a scanned item.')
  records={r['path'] for r in self.manifest.get('records',[])}
  if key not in records:raise ValueError('This item is not part of the scanned folder.')
  relative=engine.cleanrel(key);unit=relative.parts[0];applied=self.applied_map().get(unit)
  if applied:
   path=Path(applied['destination']).joinpath(*relative.parts[1:])
  else:path=self.root/relative
  engine.no_links(path.parent)
  if not path.exists() and not path.is_symlink():raise ValueError('This item no longer exists at its last known location.')
  return path
 def reveal(self,key):
  if sys.platform!='darwin':raise ValueError('Reveal in Finder is available on macOS.')
  path=self.reveal_path(key)
  try:subprocess.run(['/usr/bin/open','-R',str(path)],check=True,timeout=10)
  except subprocess.SubprocessError:raise ValueError('Finder could not reveal this item. Check that it still exists and try again.')
  return {'revealed':True}
 def choose_destination(self):
  if sys.platform!='darwin':raise ValueError('Use the destination path field on this system.')
  try:
   result=subprocess.run(['/usr/bin/osascript','-e','POSIX path of (choose folder with prompt "Choose or create a dedicated Atlas destination folder inside Documents, Desktop, Movies, Pictures, or Music")'],capture_output=True,text=True,timeout=120)
  except subprocess.TimeoutExpired:raise ValueError('The folder chooser timed out. Try again when you are ready.')
  if result.returncode:
   if '-128' in result.stderr:return {'cancelled':True}
   raise ValueError('The folder chooser could not open. You can enter the destination path instead.')
  path=engine.no_links(Path(result.stdout.strip()))
  if not any((self.home/n) in path.parents for n in ('Documents','Desktop','Movies','Pictures','Music')):raise ValueError('Choose or create a dedicated subfolder inside Documents, Desktop, Movies, Pictures, or Music.')
  if path==self.root or self.root in path.parents or path in self.root.parents:raise ValueError('The destination must be outside the folder you are organizing.')
  return {'path':str(path)}
 def canonical(self,plan,allow_projects):
  if self.manifest.get('rootProject'):raise ValueError('This folder is itself a project. Scan its parent to organize the whole project without splitting its contents.')
  if not isinstance(plan,dict) or plan.get('schemaVersion')!=1 or plan.get('sourceRoot')!=str(self.root):raise ValueError('The plan does not match this folder snapshot.')
  value=plan.get('destinationRoot')
  if not isinstance(value,str) or '\x00' in value or not Path(value).is_absolute() or '..' in Path(value).parts:raise ValueError('Choose an absolute destination inside Documents, Desktop, Movies, Pictures or Music.')
  dest=engine.no_links(Path(value));allowed=[self.home/n for n in ('Documents','Desktop','Movies','Pictures','Music')]
  if not any(base in dest.parents for base in allowed):raise ValueError('Choose a dedicated folder inside Documents, Desktop, Movies, Pictures or Music.')
  if dest==self.root or self.root in dest.parents or dest in self.root.parents:raise ValueError('Source and destination must not contain each other.')
  raw=plan.get('actions')
  if not isinstance(raw,list) or not raw or len(raw)>len(self.units):raise ValueError('There are no pending actions to apply, or the action list is invalid.')
  actions=[];seen=set();applied=self.applied_map()
  for action in raw:
   if not isinstance(action,dict):raise ValueError('Invalid plan action.')
   source=action.get('source');engine.cleanrel(source,unit=True)
   if source in seen or source not in self.units:raise ValueError('Unknown or repeated source in the plan.')
   seen.add(source);u=self.units[source]
   if source in applied:raise ValueError('Already applied: '+source+'. Restore this item before creating another action for it.')
   if not u['hashComplete'] or u.get('kind')=='link' or any('symbolic link' in w for w in u.get('warnings',[])):raise ValueError('This source contains a symbolic link or has an incomplete scan: '+source)
   if action.get('fingerprint')!=u['fingerprint']:raise ValueError('The source fingerprint does not match the snapshot: '+source)
   if action.get('action') not in ('trash','move'):raise ValueError('Only Move and Trash actions can be applied.')
   if u.get('locked') and not allow_projects:raise ValueError('Review project warnings and explicitly enable project actions before verification.')
   if u.get('warnings') and not action.get('reviewed'):raise ValueError('Review the project or cache warnings for '+source+' first.')
   destination=str(engine.cleanrel(action.get('destination'))) if action['action']=='move' else None
   retained=[u.get('zipKeeper') or u.get('duplicateKeeper')];retained=[r for r in retained if r]
   reviewed_copies=action.get('reviewedCopies',[])
   if not isinstance(reviewed_copies,list) or any(not isinstance(p,str) for p in reviewed_copies):raise ValueError('Invalid related-copy acknowledgement.')
   discard=action.get('discardRetained') is True
   if discard and not set(retained).issubset(set(reviewed_copies)):raise ValueError('Confirm the exact related copies before discarding both.')
   actions.append(dict(source=source,action=action['action'],destination=destination,bytes=u['bytes'],fingerprint=u['fingerprint'],hashComplete=True,locked=bool(u.get('locked')),warnings=u.get('warnings',[]),reviewed=bool(action.get('reviewed')),discardRetained=discard,reviewedCopies=[r for r in retained if r in reviewed_copies] if discard else [],retain=retained,retainFingerprints={r:self.units[r]['fingerprint'] for r in retained}))
  return dict(schemaVersion=1,sourceRoot=str(self.root),destinationRoot=str(dest),scannedAt=self.manifest['scannedAt'],actions=actions)
 def verify(self,plan,allow_projects=False):
  with self.lock:
   if any(j['state'] in BUSY for j in self.jobs.values()):raise ValueError('Another verification or batch is running. Wait for it to finish.')
   clean=self.canonical(plan,bool(allow_projects));ident=uuid.uuid4().hex;j=dict(id=ident,createdAt=time.time(),state='verifying',destinationRoot=clean['destinationRoot'],actions=clean['actions'],allowProjects=bool(allow_projects),output=[],verified=0,error=None,reviewToken=secrets.token_urlsafe(24));self.jobs[ident]=j;self._save(j);p=self._folder(ident)/'plan.json';p.write_text(json.dumps(clean,ensure_ascii=False));os.chmod(p,0o600);self._start(j,'verify');return self.public(j)
 def command(self,j,mode):
  folder=self._folder(j['id']);cmd=[sys.executable,str(self.engine_path)];cmd+=['--undo',str(folder/'undo-log.jsonl')] if mode=='undo' else [str(folder/'plan.json'),'--log',str(folder/'undo-log.jsonl')];cmd+=['--source-root',str(self.root),'--destination-root',j['destinationRoot']]
  if j['allowProjects']:cmd+=['--allow-project-actions']
  if mode!='verify':cmd+=['--apply','--yes']
  if mode=='apply':cmd+=['--sources-file',str(folder/'selection.json')]
  if mode=='apply' and j.get('activeScope') in ('trash','move'):cmd+=['--only-action',j['activeScope']]
  return cmd
 def _subprocess(self,j,mode,on_line):
  with subprocess.Popen(self.command(j,mode),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1) as proc:
   for line in proc.stdout:on_line(line.rstrip())
   return proc.wait()
 def _start(self,j,mode):
  def work():
   try:
    def on_line(line):
     with self.lock:
      j['output']=(j.get('output',[])+[line])[-14:]
      if line.startswith('VERIFY '):j['verified']=j.get('verified',0)+1
    rc=self.runner(j,mode,on_line)
    with self.lock:
     if rc:raise ValueError(next((line.removeprefix('STOPPED: ') for line in reversed(j.get('output',[])) if line.startswith('STOPPED:')), 'The operation stopped. Review the details before retrying.'))
     if mode=='verify':j['state']='ready'
     elif mode=='apply':j['state']='completed' if all(a['source'] in self.applied_map() for a in j['actions']) else 'paused'
     else:j['state']='restore-paused' if self._applied(j) else 'restored'
     j['error']=None;j['reviewToken']=secrets.token_urlsafe(24);self._save(j)
   except Exception as e:
    with self.lock:j.update(state='failed',error=str(e),reviewToken=secrets.token_urlsafe(24));self._save(j)
  threading.Thread(target=work,daemon=True).start()
 def operate(self,ident,mode,review_token,scope='all'):
  with self.lock:
   if scope not in ('all','trash','move'):raise ValueError('Choose All, Trash, or Move actions.')
   if any(j['state'] in BUSY for j in self.jobs.values()):raise ValueError('An operation is already running.')
   j=self.jobs.get(ident)
   if not j or not secrets.compare_digest(str(review_token or ''),j['reviewToken']):raise ValueError('This review is out of date. Refresh the run and review it again.')
   public=self.public(j)
   if mode=='apply' and not public['canApply'] or mode=='undo' and not public['canUndo']:raise ValueError('This operation is not available for this run.')
   if mode=='apply' and not any(scope=='all' or a['action']==scope for a in public['nextBatch']):raise ValueError('No remaining actions match this scope.')
   # A run’s plan is immutable and is checked by the command again before any move.
   plan=json.loads((self._folder(ident)/'plan.json').read_text())
   if plan.get('actions')!=j['actions'] or plan.get('sourceRoot')!=str(self.root) or plan.get('destinationRoot')!=j['destinationRoot']:raise ValueError('The stored plan changed; verify a new plan.')
   selected=[a['source'] for a in public['nextBatch'] if scope=='all' or a['action']==scope] if mode=='apply' else [a['source'] for a in public['restoreBatch']]
   if mode=='apply':
    selection_path=self._folder(ident)/'selection.json';engine.no_links(selection_path);selection_path.write_text(json.dumps(selected));os.chmod(selection_path,0o600)
   j.update(activeSources=selected,activeScope=scope,state='applying' if mode=='apply' else 'undoing',error=None,output=[],verified=0,reviewToken=secrets.token_urlsafe(24));self._save(j);self._start(j,mode);return self.public(j)
