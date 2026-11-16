import stat,os,json,hashlib,time,zipfile,re,struct,collections,concurrent.futures
from pathlib import Path

MARKERS={'.prproj','.aep','.fig','.sketch','.psd','.ai'}
def sha(p):
 h=hashlib.sha256()
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
def fontname(p):
 # SFNT name table, including first face of TTC collections.
 try:
  with open(p,'rb') as f:
   head=f.read(12); base=0
   if head[:4]==b'ttcf':base=struct.unpack('>I',f.read(4))[0];f.seek(base);head=f.read(12)
   n=struct.unpack('>H',head[4:6])[0]; tables=f.read(n*16)
   for i in range(n):
    tag,_,off,length=struct.unpack('>4sIII',tables[i*16:(i+1)*16])
    if tag!=b'name':continue
    f.seek(off);data=f.read(length);_,count,stroff=struct.unpack('>HHH',data[:6]);names=[]
    for j in range(count):
     plat,enc,lang,nid,l,o=struct.unpack('>HHHHHH',data[6+j*12:18+j*12])
     if nid not in (1,16):continue
     raw=data[stroff+o:stroff+o+l]
     try:v=raw.decode('utf-16-be' if plat in (0,3) else 'mac_roman').strip('\0 ')
     except Exception:continue
     names.append((nid==16,lang==1033,plat==3,v))
    if names:return sorted(names,reverse=True)[0][3]
 except Exception:pass
 return None

from atlas_projects import analyze_projects
def scan(root,progress=lambda **kwargs:None,cancelled=lambda:False,exclude=()):
 ROOT=Path(root);exclude=[Path(p).resolve() for p in exclude];start=time.time()
 records=[];errors=[];excluded=[]
 progress(phase="inventory",message="Reading folders and file metadata…",completed=0,total=0)
 def walkerror(e):errors.append({'path':os.path.relpath(e.filename,ROOT),'error':str(e)})
 for root,dirs,files in os.walk(ROOT,followlinks=False,onerror=walkerror):
  dirs.sort();files.sort()
  if cancelled():raise ValueError('Scan cancelled. No files were changed.')
  skipped=[n for n in dirs if any(Path(root,n).resolve()==p or p in Path(root,n).resolve().parents for p in exclude)]
  for n in skipped:excluded.append((Path(root)/n).relative_to(ROOT).as_posix())
  dirs[:]=[n for n in dirs if n not in skipped]
  if len(records)%1000<100:progress(phase='inventory',message='Reading folders and file metadata…',completed=len(records),total=0)
  for name in list(dirs)+files:
   p=Path(root,name);rel=p.relative_to(ROOT).as_posix()
   try:
    st=p.lstat();kind='link' if stat.S_ISLNK(st.st_mode) else 'dir' if stat.S_ISDIR(st.st_mode) else 'file' if stat.S_ISREG(st.st_mode) else 'special'
    records.append(dict(path=rel,name=name,kind=kind,size=st.st_size if kind=='file' else 0,mtime=st.st_mtime,ext=p.suffix.lower(),unit=rel.split('/')[0]))
   except OSError as e:errors.append({'path':rel,'error':str(e)})
 files=[r for r in records if r['kind']=='file']
 def hashrecord(r):
  try:
   if cancelled():return
   p=ROOT/r['path'];before=p.stat()
   if before.st_size!=r['size'] or before.st_mtime!=r['mtime']:raise ValueError('changed during scan')
   r['sha256']=sha(p);after=p.stat()
   if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('changed during scan')
   if r['ext'] in {'.ttf','.otf','.ttc'}:r['family']=fontname(p)
  except Exception as e:r.pop('sha256',None);errors.append({'path':r['path'],'error':str(e)})
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  for i,_ in enumerate(pool.map(hashrecord,files)):
   if cancelled():raise ValueError('Scan cancelled. No files were changed.')
   if i%100==0:progress(phase='hashing',message='Comparing file contents for exact matches…',completed=i,total=len(files))
 by_path={r['path']:r for r in records};units={r['path']:dict(r,bytes=0,count=0,projects=[],caches=[],families=[],warnings=[],suggestion='Undecided',confidence='Low',reason='Review before deciding.') for r in records if '/' not in r['path']}
 dups=collections.defaultdict(list);families=collections.defaultdict(list);members=collections.defaultdict(list)
 for r in records:
  u=units[r['unit']];members[r['unit']].append(r)
  if r['kind']=='special':u['warnings'].append('Contains a special filesystem entry; automatic application is blocked.')
  if r['kind']=='link':u['warnings'].append('Contains a symbolic link; explicit Trash confirmation is required.')
  if r['kind']!='file':continue
  u['bytes']+=r['size'];u['count']+=1
  if r.get('sha256'):dups[r['sha256']].append(r['path'])
  if r.get('family'):families[r['family']].append(r['path'])
  if r['ext'] in MARKERS or r['name']=='package.json':u['projects'].append(r['path'])
  if re.search(r'(adobe premiere pro (audio|video) previews|media cache|media cache files|adobe after effects.*cache|disk cache)',r['path'],re.I) or r['ext'] in {'.cfa','.pek'}:u['caches'].append(r['path'])
 for name,u in units.items():
  u['families']=sorted({r['family'] for r in members[name] if r.get('family')})
  u['locked']=bool(u['projects']);u['warnings']=list(set(u['warnings']))
  if u['locked']:u['warnings'].append('Project unit: keep its contents together. External or absolute references may still break after a move; open and relink in the original application.')
  if u['caches']:u['warnings'].append('Cache candidate: confirm the owning project is closed and these are regenerable, not captured source media.')
  # Canonical content fingerprint includes directory entries and link presence.
  h=hashlib.sha256()
  for r in sorted(members[name],key=lambda x:x['path']):
   part=r['path'][len(name):].lstrip('/')
   h.update((json.dumps([part,r['kind'],r['size'],r.get('sha256','')],ensure_ascii=False,separators=(',',':'))+'\n').encode())
  u['fingerprint']=h.hexdigest();u['hashComplete']=all(r.get('sha256') for r in members[name] if r['kind']=='file') and not any(r['kind']=='special' for r in members[name]) and not any(e['path']==name or e['path'].startswith(name+'/') or e['path']=='.' for e in errors)
  if u['locked']:u.update(suggestion='Move',confidence='Medium',reason='Contains project source files. Move only as a complete unit after reviewing linked assets.',target='Projects')
  elif u['families']:u.update(suggestion='Move',confidence='High',reason='Font families identified from embedded font name tables.',target='Design Library/Fonts')
  elif u['ext'] in {'.png','.jpg','.jpeg','.svg','.webp','.eps'}:u.update(suggestion='Move',confidence='Medium',reason='Standalone visual asset; check whether a project references it.',target='Design Library/Images')
  elif u['ext']=='.pdf':u.update(suggestion='Move',confidence='Medium',reason='PDF document; review its subject before filing.',target='Documents')
  elif u['ext'] in {'.mp4','.mov','.webm','.mkv','.mp3','.wav'}:u.update(suggestion='Move',confidence='Medium',reason='Media file; verify it is not linked by a project.',target='Media')
  elif u['ext'] in {'.zip','.rar','.7z'}:u.update(suggestion='Move',confidence='Medium',reason='Archive; keep until contents and extracted copies are verified.',target='Archives')
  if u['caches'] and not u['locked']:u.update(suggestion='Trash',confidence='Medium',reason='Possible generated Premiere/AE cache. Confirm ownership and regeneration before accepting.')
 apps=[]
 for ap in [Path('/Applications'),Path.home()/'Applications']:
  if ap.exists():apps += [p.stem for p in ap.glob('*.app')]
 def normalize(s):return re.sub('[^a-z0-9]','',s.lower())
 for u in units.values():
  if u['ext']=='.dmg':
   matches=[a for a in apps if len(normalize(a))>=4 and normalize(a) in normalize(u['name'])]
   u['installedApps']=matches
   if matches:u.update(suggestion='Trash',confidence='Medium',reason='Installer filename matches installed app: '+', '.join(matches)+'. This does not verify the disk image contents or application version.')
   else:u.update(reason='No confident installed application filename match. Keep for manual review.')
 progress(phase='archives',message='Checking ZIP twins and relationships…',completed=0,total=0)
 # Complete ZIP-to-folder comparison. No extraction and no writes to Downloads.
 zipmatches=[];ziperrors=[]
 for r in files:
  if cancelled():raise ValueError('Scan cancelled. No files were changed.')
  if r['ext']!='.zip':continue
  try:
   with zipfile.ZipFile(ROOT/r['path']) as z:
    entries=[x for x in z.infolist() if not x.is_dir() and not x.filename.startswith('__MACOSX/') and Path(x.filename).name!='.DS_Store']
    if not entries:continue
    total=sum(x.file_size for x in entries)
    if total>4*1024**3 or total>max(r['size']*300,50*1024**2):ziperrors.append({'path':r['path'],'reason':'Skipped decompression safety limit'});continue
    if any(x.flag_bits&1 for x in entries):raise ValueError('encrypted ZIP')
    names=[x.filename.rstrip('/') for x in entries]
    if len(set(names))!=len(names):raise ValueError('ZIP contains repeated member names; twin comparison requires manual review')
    prefix=names[0].split('/')[0]+'/'
    common=all(n.startswith(prefix) for n in names)
    candidates=[u for u in units.values() if u['kind']=='dir' and (normalize(u['name'])==normalize(Path(r['name']).stem) or common and normalize(u['name'])==normalize(prefix[:-1]))]
    for u in candidates:
     dest={x['path'][len(u['path'])+1:]:x for x in members[u['path']] if x['kind']=='file' and x['name']!='.DS_Store' and '/__MACOSX/' not in x['path']}
     for strip in ([False,True] if common else [False]):
      mapped={x.filename[len(prefix):] if strip else x.filename:x for x in entries}
      if set(mapped)!=set(dest) or any(mapped[n].file_size!=dest[n]['size'] for n in mapped):continue
      good=True
      for n,entry in mapped.items():
       h=hashlib.sha256()
       with z.open(entry) as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
       if h.hexdigest()!=dest[n].get('sha256'):good=False;break
      if good:zipmatches.append({'zip':r['path'],'folder':u['path'],'verified':True,'files':len(mapped)});break
  except Exception as e:ziperrors.append({'path':r['path'],'reason':str(e)})
 # Never suggest removing a duplicate when its only surviving copy is also suggested for removal.
 dupgroups=[v for v in dups.values() if len(v)>1]
 for paths in dupgroups:
  loose=sorted([p for p in paths if '/' not in p and units[p]['kind']=='file'])
  if not loose:continue
  keeper=loose[0]
  for p in loose[1:]:
   u=units[p]
   if not u['locked']:u.update(suggestion='Trash',confidence='High',reason='Exact SHA-256 duplicate of '+keeper+'. The original must remain in the final plan.',duplicateKeeper=keeper)
 for m in zipmatches:
  u=units[m['zip'].split('/')[0]]
  if u['path']==m['zip'] and not u['locked']:u.update(suggestion='Trash',confidence='High',reason='All non-metadata ZIP files match extracted folder '+m['folder']+' by size and SHA-256. Keep the extracted folder.',zipKeeper=m['folder'])
 result={'version':1,'root':str(ROOT),'home':str(Path.home()),'scannedAt':time.time(),'units':list(units.values()),'records':records,'duplicates':dupgroups,'zipMatches':zipmatches,'fontFamilies':dict(families),'applications':apps,'errors':errors,'zipErrors':ziperrors,'limitations':['Project membership is inferred from folder containment; external and absolute links are not exhaustively resolved.','ZIP matches compare basename/root-name candidate folders and exclude macOS metadata; nonmatching names are not exhaustively searched.','DMG matches use installer and installed application names, not mounted image contents.','All top-level folders are decision units to preserve project and asset relationships. Symbolic links are not followed. Linked units require explicit Trash confirmation; moving them remains blocked.']}
 result['decisionIdentityVersion']=1
 result['excluded']=excluded
 for u in result['units']:
  if any(p==u['path'] or p.startswith(u['path']+'/') for p in excluded):
   u['hashComplete']=False;u['suggestion']='Keep';u['reason']='Contains Atlas itself. Its running files are excluded from this scan.';u['warnings'].append(u['reason'])
 progress(phase='relationships',message='Tracing project imports, assets and possible leftovers…',completed=0,total=0)
 analyze_projects(result,cancelled)
 return result
