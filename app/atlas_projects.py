"""Read-only, bounded static project analysis. Never imports or executes scanned code."""
import collections,gzip,hashlib,html,json,os,re,time
from pathlib import Path
CODE={'.js','.jsx','.ts','.tsx','.mjs','.cjs','.vue','.svelte','.css','.scss','.html','.py'}
GENERATED={'node_modules','.git','.next','.nuxt','.cache','__pycache__','.venv','venv','dist','build','coverage','.turbo'}
SENSITIVE={'.env','.npmrc','.pypirc','credentials','id_rsa','id_ed25519'}
def analyze_projects(d,cancelled=lambda:False):
 root=Path(d['root']);records={r['path']:r for r in d['records']};units={u['path']:u for u in d['units']};refs=[];projects=[];findings=[];inbound=collections.defaultdict(set);unresolved=0;skipped=0
 def clean(path):
  try:return Path(os.path.normpath(str(path))).relative_to(root).as_posix()
  except ValueError:return None
 def ref(a,b,kind):
  if a==b:return
  key=(a,b,kind)
  if key not in seen:seen.add(key);refs.append({'project':a,'asset':b,'kind':kind});inbound[b].add(a)
 seen=set()
 markers=[r for r in records.values() if r['kind']=='file' and not set(Path(r['path']).parts)&GENERATED and (r['name'] in {'package.json','pyproject.toml','requirements.txt','Cargo.toml','go.mod'} or r['ext'] in {'.prproj','.aep','.fig','.sketch'})]
 rootmarkers=[p.name for p in root.iterdir() if p.is_file() and (p.name in {'package.json','pyproject.toml','Cargo.toml','go.mod'} or p.suffix.lower() in {'.prproj','.aep'})]
 if (root/'.git').exists():rootmarkers.append('.git')
 if (root/'requirements.txt').is_file() and any(root.glob('*.py')):rootmarkers.append('requirements.txt + Python sources')
 d['rootProject']=bool(rootmarkers);d['rootProjectMarkers']=rootmarkers
 for r in markers:
  projects.append({'path':str(Path(r['path']).parent),'marker':r['path'],'unit':r['unit'],'kind':'Web / code' if r['name']=='package.json' else 'Creative / code','dependencies':[]})
 for r in records.values():
  if r['kind']=='dir' and r['name']=='.git' and not set(Path(r['path']).parts[:-1])&GENERATED:projects.append({'path':str(Path(r['path']).parent),'marker':r['path'],'unit':r['unit'],'kind':'Git repository','dependencies':[]})
 aliases={}
 for p in projects:
  if Path(p['marker']).name!='package.json':continue
  try:
   if records[p['marker']]['size']>1024*1024:continue
   data=json.loads((root/p['marker']).read_text());p['name']=str(data.get('name') or p['path']);p['dependencies']=sorted(set((data.get('dependencies') or {}))|set((data.get('devDependencies') or {})))
   for name,value in {**(data.get('dependencies') or {}),**(data.get('devDependencies') or {})}.items():
    if isinstance(value,str) and value.startswith(('file:','link:')):
     target=clean(root/p['path']/value.split(':',1)[1]);marker=(target+'/package.json') if target and target!='.' else 'package.json'
     if marker in records:ref(p['marker'],marker,'Project local dependency')
   for cfg in ('tsconfig.json','jsconfig.json'):
    f=root/p['path']/cfg
    if f.is_file() and not f.is_symlink() and f.stat().st_size<1024*1024:
     try:
      config=json.loads(f.read_text()).get('compilerOptions',{});base=root/p['path']/config.get('baseUrl','.');aliases[p['path']]=[(k.rstrip('*'),base/v[0].rstrip('*')) for k,v in config.get('paths',{}).items() if isinstance(v,list) and v and isinstance(v[0],str)]
     except (ValueError,OSError,AttributeError):pass
  except (ValueError,OSError,TypeError,AttributeError):pass
 projectpaths={}
 for p in projects:projectpaths.setdefault(p['path'],p)
 for r in records.values():
  if cancelled():raise ValueError('Scan cancelled. No files were changed.')
  if r['kind']!='file':continue
  path=r['path'];parts=Path(path).parts
  if set(parts)&GENERATED or any(n in SENSITIVE or n.startswith('.env.') or n.endswith(('.pem','.key')) for n in parts):continue
  if r['ext'] not in CODE|{'.prproj'}:continue
  if r['size']>1024*1024:skipped+=1;continue
  try:
   raw=(root/path).read_bytes()
   if r['ext']=='.prproj':
    if raw[:2]==b'\x1f\x8b':
     with gzip.open(root/path,'rb') as f:raw=f.read(8*1024*1024+1)
    text=raw.decode('utf8','ignore');values=[html.unescape(v) for _,v in re.findall(r'<(ActualMediaFilePath|FilePath|RelativePath|MediaFilePath)[^>]*>(.*?)</\1>',text,re.S)]
   else:text=raw.decode('utf8','ignore');values=re.findall(r'''["']([^"'\n]{1,512})["']''',text)
   parent=Path(path).parent;owner=next((projectpaths[str(q)] for q in [parent,*parent.parents] if str(q) in projectpaths),None)
   for value in values:
    value=value.split('?')[0].split('#')[0]
    if not value or value.startswith(('http:','https:','data:','mailto:')):continue
    candidates=[]
    if r['ext']=='.prproj':candidates=[Path(value),root/Path(path).parent/value,root/value]
    elif value.startswith('.') :candidates=[root/Path(path).parent/value]
    elif value.startswith('/') :candidates=[root/value.lstrip('/')]+([root/owner['path']/'public'/value.lstrip('/'),root/owner['path']/value.lstrip('/')] if owner else [])
    elif owner:
     candidates=[dest/value[len(prefix):] for prefix,dest in aliases.get(owner['path'],[]) if value.startswith(prefix)]
    if not candidates:continue
    matched=False
    for candidate in candidates:
     key=clean(candidate)
     if key is None:continue
     options=[key]+[key+e for e in CODE|{'.json','.png','.jpg','.svg'}]+[key+'/index'+e for e in CODE]
     found=next((k for k in options if k in records and records[k]['kind']=='file'),None)
     if found:ref(path,found,'Premiere media reference' if r['ext']=='.prproj' else 'Project import / asset');matched=True;break
    if not matched:unresolved+=1
  except (OSError,ValueError,EOFError):skipped+=1
 for a in refs:
  if a['project'].split('/')[0]!=a['asset'].split('/')[0]:
   u=units[a['asset'].split('/')[0]];warning='Known project reference from '+a['project']+'. Moving or trashing this unit can break that project.'
   if warning not in u['warnings']:u['warnings'].append(warning)
   u.update(suggestion='Keep',confidence='High',reason=warning)
 signatures=collections.defaultdict(list);byunit=collections.defaultdict(list);projectbyunit=collections.defaultdict(list);refcounts=collections.Counter(a['project'].split('/')[0] for a in refs);incomingunits={a['asset'].split('/')[0] for a in refs}
 for p in projects:projectbyunit[p['unit']].append(p)
 for r in records.values():
  if r["kind"]=="file":byunit[r["unit"]].append(r)
 for u in units.values():
  files=byunit[u['path']];source=[r for r in files if not set(Path(r['path']).parts)&GENERATED and not r['name'].startswith('.env') and r['name'] not in SENSITIVE]
  generated=[r for r in files if set(Path(r['path']).parts)&GENERATED];p=projectbyunit[u['path']]
  u['projectInfo']={'projects':p,'generatedBytes':sum(r['size'] for r in generated),'staticReferences':refcounts[u['path']]}
  if p and not u['locked']:
   u['locked']=True;u['projects']=[x['marker'] for x in p];u['warnings'].append('Project unit: keep this code project and its dependencies together. External references may need relinking.');u.update(suggestion='Move',confidence='Medium',reason='Contains code project manifests. Review local dependencies and keep the complete folder intact.',target='Projects')
  if p and source and all(r.get('sha256') for r in source):
   signature=hashlib.sha256(json.dumps(sorted((r['path'][len(u['path']):],r['sha256']) for r in source)).encode()).hexdigest();signatures[signature].append(u['path'])
  if generated:
   findings.append({'unit':u['path'],'kind':'generated','title':'Generated dependencies & build files','confidence':'Medium','bytes':sum(r['size'] for r in generated),'reason':'Contains '+', '.join(sorted({n for r in generated for n in Path(r['path']).parts if n in GENERATED}))+'. These are often rebuildable, but may contain uncommitted work or a required offline environment. The enclosing folder stays intact.'})
  if u['kind']=='dir' and not p and not u['locked'] and re.search(r'(^|[-_ ])(old|backup|copy|temp|test|untitled|export|output|draft)([-_ .]|$)|\(\d+\)$',u['name'],re.I) and u['path'] not in incomingunits:
   findings.append({'unit':u['path'],'kind':'leftover','title':'Possible project leftover','confidence':'Low','bytes':u['bytes'],'reason':'Name suggests an export, copy or temporary folder. No incoming reference was resolved within this scan. External projects, dynamic loading and unsupported formats can still use it. Review before deciding.'})
  if p:
   assets=[r for r in source if r['ext'] in {'.png','.jpg','.jpeg','.svg','.webp','.mp4','.wav'} and r['path'] not in inbound]
   if assets:findings.append({'unit':u['path'],'kind':'unreferenced','title':'Assets to review inside this project','confidence':'Low','bytes':sum(r['size'] for r in assets),'paths':[r['path'] for r in assets[:40]],'count':len(assets),'reason':'No static incoming reference was resolved for these assets in this scan. Public assets, dynamic URLs, content files and external tools may still use them. This does not prove they are orphaned; the project remains an intact unit.'})
  if d['rootProject']:
   u['locked']=True;u['warnings'].append('The selected folder is itself a project. Individual child actions are blocked to keep the project intact. Scan its parent folder to organize the whole project.');u.update(suggestion='Keep',confidence='High',reason=u['warnings'][-1])
 d['projectTwins']=[paths for paths in signatures.values() if len(paths)>1]
 for paths in d['projectTwins']:
  for unit in paths:findings.append({'unit':unit,'kind':'project-copy','title':'Matching project source tree','confidence':'High','bytes':units[unit]['bytes'],'related':[p for p in paths if p!=unit],'reason':'Relative source file paths and SHA-256 hashes match another project. Generated folders, Git history and environment settings were excluded, so the complete folders may differ. Compare before removing a copy.'})
 d.update(projectReferences=refs,projects=projects,projectFindings=findings,analysisCoverage={'resolvedReferences':len(refs),'unresolvedCandidates':unresolved,'skippedLargeOrUnreadableSources':skipped,'externalReferencesChecked':False})
 d['limitations'].append('Code analysis resolves bounded static local imports, common path aliases, public assets and local package dependencies. Dynamic references and use by projects outside this scan cannot be ruled out. No code or package scripts are executed; secret configuration contents are not analyzed.')
