#!/usr/bin/env python3
"""Apply an organizer plan. Dry-run by default. Same-volume, no-overwrite moves only."""
import argparse,ctypes,errno,hashlib,json,os,sys,time,unicodedata,uuid
from pathlib import Path
MARKERS={'.prproj','.aep','.fig','.sketch','.psd','.ai'}
def digest(p):
 h=hashlib.sha256()
 with os.fdopen(os.open(p,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0)),'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def cleanrel(s,unit=False):
 if not isinstance(s,str) or not s or '\\' in s or any(ord(c)<32 for c in s):raise ValueError('Invalid relative path')
 p=Path(s)
 if p.is_absolute() or any(v in ('','.','..') for v in s.split('/')) or unit and len(p.parts)!=1:raise ValueError('Unsafe path: '+s)
 return p

def no_links(p):
 p=Path(os.path.abspath(p))
 for q in [p,*p.parents]:
  if q.is_symlink():raise ValueError('Symbolic link is not allowed: '+str(q))
 return p

def present(p):return os.path.lexists(p)

def fingerprint(p,symlink_targets=None):
 # Only an explicit Trash override supplies a nonempty, pinned link inventory.
 links_allowed=isinstance(symlink_targets,dict) and bool(symlink_targets)
 no_links(p.parent if links_allowed else p)
 if not present(p):raise ValueError('Missing source: '+str(p))
 paths=[p]
 if not p.is_symlink() and p.is_dir():
  for root,ds,fs in os.walk(p,followlinks=False):
   paths.extend(Path(root,n) for n in ds+fs)
 rows=[];locked=False;observed={}
 for q in paths:
  rel='' if q==p else q.relative_to(p).as_posix()
  no_links(q.parent)
  if q.is_symlink():
   if not links_allowed:raise ValueError('Symbolic link in source: '+str(q))
   observed[rel]=os.readlink(q);kind,size,h='link',0,''
  elif q.is_dir():kind,size,h='dir',0,''
  elif q.is_file():
   before=q.stat();kind,size,h='file',before.st_size,digest(q);after=q.stat()
   if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('File changed during verification: '+str(q))
   locked |= q.suffix.lower() in MARKERS or q.name=='package.json'
  else:raise ValueError('Unsupported special file: '+str(q))
  rows.append((rel,kind,size,h))
 if links_allowed and observed!=symlink_targets:raise ValueError('Symbolic links changed since verification: '+str(p))
 h=hashlib.sha256()
 for row in sorted(rows,key=lambda r:r[0]):h.update((json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n').encode())
 return h.hexdigest(),locked

def rename_exclusive(src,dst,allow_symlink=False):
 """Kernel-enforced no overwrite, never copy/delete or cross volume."""
 no_links(src.parent if allow_symlink else src);no_links(dst.parent)
 if dst.exists() or dst.is_symlink():raise FileExistsError(str(dst))
 libc=ctypes.CDLL(None,use_errno=True)
 if sys.platform=='darwin':
  fn=libc.renamex_np;fn.argtypes=[ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint];rc=fn(os.fsencode(src),os.fsencode(dst),4) # RENAME_EXCL
 elif sys.platform.startswith('linux') and hasattr(libc,'renameat2'):
  fn=libc.renameat2;fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];rc=fn(-100,os.fsencode(src),-100,os.fsencode(dst),1)
 else:raise RuntimeError('No safe exclusive rename available on this OS')
 if rc!=0:
  e=ctypes.get_errno()
  if e==errno.EXDEV:raise ValueError('Cross-volume move refused; use a destination on the same volume')
  raise OSError(e,os.strerror(e),str(src))

def append(log,event):
 log.parent.mkdir(parents=True,exist_ok=True);no_links(log)
 flags=os.O_WRONLY|os.O_CREAT|os.O_APPEND|getattr(os,'O_NOFOLLOW',0)
 fd=os.open(log,flags,0o600)
 with os.fdopen(fd,'a') as f:f.write(json.dumps(dict(time=time.time(),**event),ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())

def readlog(path):
 if not path.exists():return []
 no_links(path)
 return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

def check_under(p,root):
 if p==root or root not in p.parents:raise ValueError('Path escapes allowed root: '+str(p))

def undo(args):
 log=Path(args.undo).absolute();events=readlog(log);intents={e['id']:e for e in events if e['event']=='intent'};undone={e['id'] for e in events if e['event']=='undone'}
 if not intents:raise ValueError('No journaled actions found')
 n=0
 for op in reversed(list(intents.values())):
  if op['id'] in undone:continue
  src,dst=Path(op['source']),Path(op['destination'])
  allowed_source=no_links(Path(args.source_root).absolute());allowed_dest=no_links(Path(args.destination_root).absolute());allowed_trash=no_links(Path.home()/'.Trash')
  link_override=op.get('allowSymlinkTrash') is True and op.get('action')=='trash' and dst.parent==allowed_trash
  targets=op.get('symlinkTargets') if link_override else None
  no_links(src.parent if link_override else src);no_links(dst.parent if link_override else dst)
  check_under(src,allowed_source)
  if src.parent!=allowed_source:raise ValueError('Undo source must be a top-level decision unit')
  if allowed_dest not in dst.parents and dst.parent!=allowed_trash:raise ValueError('Undo destination outside allowed roots')
  # A journal can contain a pending intent if interrupted just before/after rename.
  if present(src) and not present(dst):
   if fingerprint(src,targets)[0]!=op['fingerprint']:raise ValueError('Original path contains changed content; undo refused: '+str(src))
   print('Already at original location:',src)
   if args.apply:append(log,dict(event='undone',id=op['id'],note='already-original'))
   continue
  if present(src) or not present(dst):raise ValueError('Ambiguous journal state; inspect manually: '+str(src))
  if fingerprint(dst,targets)[0]!=op['fingerprint']:raise ValueError('Moved item changed; undo refused: '+str(dst))
  print('UNDO',dst,'→',src)
  if args.apply:
   no_links(src.parent)
   if not src.parent.is_dir():raise ValueError('Original parent missing')
   append(log,dict(event='undo-intent',id=op['id']))
   rename_exclusive(dst,src,allow_symlink=link_override);append(log,dict(event='undone',id=op['id']))
  n+=1
  if getattr(args,'max_actions',None) and n>=args.max_actions:break
  if n%args.batch_size==0 and not args.yes and input('Continue next undo batch? [y/N] ').lower()!='y':break
 print('Undo actions',n,'(applied)' if args.apply else '(dry run)')

def run(args):
 planpath=Path(args.plan).absolute();raw=planpath.read_bytes();plan=json.loads(raw);planid=hashlib.sha256(raw).hexdigest()
 if plan.get('schemaVersion')!=1:raise ValueError('Unsupported schema')
 root=no_links(Path(args.source_root).absolute());dest=no_links(Path(args.destination_root).absolute())
 if root!=Path(plan['sourceRoot']) or dest!=Path(plan['destinationRoot']):raise ValueError('Plan roots must exactly match command-line roots')
 if root==dest or root in dest.parents or dest in root.parents:raise ValueError('Source and destination must not contain each other')
 trash=no_links(Path.home()/'.Trash')
 if dest==trash or trash in dest.parents:raise ValueError('Use Trash actions for Trash destinations')
 if dest==Path.home() or dest==Path('/'):raise ValueError('Choose a dedicated destination folder')
 log=no_links(Path(args.log).absolute())
 if log==root or root in log.parents or log==dest or dest in log.parents or log==trash or trash in log.parents:raise ValueError('Keep the journal outside source, destination, and Trash')
 events=readlog(log);foreign=[e for e in events if e.get('plan') and e['plan']!=planid]
 if foreign:raise ValueError('Journal belongs to a different plan. Use a new log path.')
 if any(e['event'] in {'undone','undo-intent'} for e in events):raise ValueError('This journal has undo history. Export a fresh plan and use a new log.')
 done={e['source'] for e in events if e['event']=='done'}
 # Refuse ambiguous pending operations. Undo command can recover them safely.
 completed_ids={e['id'] for e in events if e['event']=='done'}
 if any(e['event']=='intent' and e['id'] not in completed_ids for e in events):raise ValueError('Interrupted action in log. Run --undo on this journal before retrying.')
 actions=plan.get('actions');sources=set();targets=set();prepared=[]
 if not isinstance(actions,list):raise ValueError('Invalid action list')
 selection_file=getattr(args,'sources_file',None);selected_sources=None
 if selection_file:
  selected_sources=json.loads(Path(selection_file).read_text())
  if not isinstance(selected_sources,list) or any(not isinstance(s,str) for s in selected_sources):raise ValueError('Invalid source selection')
  selected_sources=set(str(cleanrel(s,unit=True)) for s in selected_sources)
  if not selected_sources.issubset({a.get('source') for a in actions}):raise ValueError('Source selection is not part of this plan')
 selected_actions=[a for a in actions if (not getattr(args,'only_action',None) or a.get('action')==args.only_action) and (selected_sources is None or a.get('source') in selected_sources)]
 trash_sources={a.get('source') for a in selected_actions if a.get('action')=='trash'}
 for a in selected_actions:
  source=cleanrel(a['source'],unit=True);src=root/source
  if str(src) in sources:raise ValueError('Duplicate source in plan')
  sources.add(str(src))
  if a['action'] not in ('move','trash'):raise ValueError('Unsupported action')
  link_override=a.get('allowSymlinkTrash') is True
  if link_override and (a['action']!='trash' or not getattr(args,'allow_symlink_trash',False)):raise ValueError('Symbolic-link Trash requires explicit --allow-symlink-trash; moving linked units is not enabled')
  link_targets=a.get('symlinkTargets') if link_override else None
  if link_override and (not isinstance(link_targets,dict) or not link_targets or any(not isinstance(k,str) or not isinstance(v,str) for k,v in link_targets.items())):raise ValueError('Check the symbolic links in Atlas before applying or exporting this plan')
  if not a.get('hashComplete'):raise ValueError('Incomplete scan: '+str(src))
  for retained in a.get('retain',[]):
   retained=str(cleanrel(retained,unit=True))
   if a.get('discardRetained') is True and retained in a.get('reviewedCopies',[]):continue
   if retained in trash_sources:raise ValueError('Both related copies would be trashed: '+retained)
   keep=root/retained
   if not keep.exists():
    moved=[e for e in events if e['event']=='done' and e['source']==str(keep)]
    if not moved or not Path(moved[-1]['destination']).exists():raise ValueError('Retained copy is missing: '+retained)
    keep=Path(moved[-1]['destination'])
   expected=a.get('retainFingerprints',{}).get(retained)
   if not expected or fingerprint(keep)[0]!=expected:raise ValueError('Retained copy changed or lacks verification: '+retained)
  if str(src) in done:continue
  if a['action']=='move':dst=dest/cleanrel(a['destination']);check_under(dst,dest)
  else:dst=trash/(src.name+'.organizer-'+uuid.uuid4().hex[:10])
  no_links(dst)
  key=unicodedata.normalize('NFC',str(dst)).casefold()
  if key in targets or dst.exists():raise ValueError('Destination collision: '+str(dst))
  targets.add(key)
  print('VERIFY',src,flush=True);fp,locked=fingerprint(src,link_targets)
  if fp!=a['fingerprint']:raise ValueError('Source changed since scan: '+str(src))
  if (locked or a.get('locked')) and not args.allow_project_actions:raise ValueError('Project action requires --allow-project-actions after reviewing linked assets: '+str(src))
  if (a.get('warnings') or locked) and not a.get('reviewed'):raise ValueError('Warnings not reviewed in app: '+str(src))
  # Prevent replacing the file that supplies the current plan/journal.
  if src==planpath or src in planpath.parents:raise ValueError('Plan resides inside an action source')
  prepared.append((a,src,dst))
 print(len(prepared),'pending actions;',len(done),'previously applied. No permanent deletes.')
 if not args.apply:
  for a,src,dst in prepared:print(a['action'].upper(),src,'→',dst)
  print('DRY RUN ONLY. Add --apply to execute.');return
 if not prepared:return
 n=0
 for a,src,dst in prepared:
  if getattr(args,'max_actions',None) and n>=args.max_actions:break
  if n%args.batch_size==0:
   if not args.yes and input('Apply next '+str(min(args.batch_size,len(prepared)-n))+' actions? [y/N] ').lower()!='y':break
  # Recheck retained copies, including ones moved earlier in this run.
  current_events=readlog(log)
  for retained in a.get('retain',[]):
   if a.get('discardRetained') is True and retained in a.get('reviewedCopies',[]):continue
   keep=root/retained
   if not keep.exists():
    moved=[e for e in current_events if e['event']=='done' and e['source']==str(keep)]
    if not moved:raise ValueError('Retained copy missing: '+retained)
    keep=Path(moved[-1]['destination'])
   if fingerprint(keep)[0]!=a['retainFingerprints'][retained]:raise ValueError('Retained copy changed: '+retained)
  no_links(dst.parent);dst.parent.mkdir(parents=True,exist_ok=True);no_links(dst.parent)
  if src.lstat().st_dev!=dst.parent.stat().st_dev:raise ValueError('Cross-volume move refused')
  # Verify again immediately before the journal and atomic rename.
  link_override=a.get('allowSymlinkTrash') is True
  if fingerprint(src,a.get('symlinkTargets') if link_override else None)[0]!=a['fingerprint']:raise ValueError('Source changed after preflight: '+str(src))
  ident=uuid.uuid4().hex;event=dict(id=ident,plan=planid,source=str(src),destination=str(dst),fingerprint=a['fingerprint'],action=a['action'])
  if link_override:event.update(allowSymlinkTrash=True,symlinkTargets=a['symlinkTargets'])
  append(log,dict(event='intent',**event));rename_exclusive(src,dst,allow_symlink=link_override);append(log,dict(event='done',**event));n+=1;print('APPLIED',a['action'],src.name,flush=True)
 print('Applied',n,'actions. Journal:',log)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('plan',nargs='?');p.add_argument('--apply',action='store_true');p.add_argument('--undo',metavar='LOG');p.add_argument('--source-root',default=str(Path.home()/'Downloads'));p.add_argument('--destination-root',default=str(Path.home()/'Documents'/'Organized Downloads'));p.add_argument('--log',default=str(Path(__file__).resolve().parent/'undo-log.jsonl'));p.add_argument('--batch-size',type=int,default=25);p.add_argument('--sources-file',help='JSON list of reviewed source names to apply from this plan');p.add_argument('--only-action',choices=['trash','move'],help='Apply only this action type from the plan');p.add_argument('--max-actions',type=int,help='Apply or undo at most this many actions');p.add_argument('--yes',action='store_true',help='Skip batch prompts');p.add_argument('--allow-project-actions',action='store_true');p.add_argument('--allow-symlink-trash',action='store_true',help='Allow explicitly reviewed link-containing items to go to Trash without following their links');args=p.parse_args()
 if args.max_actions is not None and args.max_actions<1:p.error('--max-actions must be positive')
 if args.batch_size<1:p.error('--batch-size must be positive')
 if not args.undo and not args.plan:p.error('Provide a plan JSON, or --undo LOG')
 try:undo(args) if args.undo else run(args)
 except (Exception,KeyboardInterrupt) as e:print('STOPPED:',e,file=sys.stderr);return 1
 return 0
if __name__=='__main__':sys.exit(main())
