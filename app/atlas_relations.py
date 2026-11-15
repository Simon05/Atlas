"""Explainable relationship summaries. Matching bytes never imply a live dependency."""
import collections,itertools,re
from pathlib import PurePosixPath
GENERATED={'node_modules','.git','.next','.nuxt','.cache','__pycache__','.venv','venv','dist','build','coverage','.turbo','vendor','.pnpm','.yarn','site-packages','Pods'}
COMMON={'package-lock.json','yarn.lock','pnpm-lock.yaml','bun.lockb','LICENSE','LICENSE.md','LICENSE.txt','COPYING','.gitignore','.gitattributes','.editorconfig'}
def background(path):
 p=PurePosixPath(path);return bool(re.fullmatch(r'(fonts?\.txt|licen[cs]e([ ._-].*)?|read[ _-]?me(\..*)?)',p.name,re.I)) or bool(set(p.parts)&GENERATED) or p.name in COMMON or p.name.startswith('._')
def build_relations(d):
 records={r['path']:r for r in d['records']};units={u['path'] for u in d['units']};pairs={};stats=collections.Counter()
 def add(a,b,kind,sample,count=1,bytes_=0,from_=None,to=None):
  if a==b or a not in units or b not in units:return
  a,b=sorted((a,b));pair=pairs.setdefault((a,b),{'a':a,'b':b,'relations':{}});key=(kind,from_,to)
  rel=pair['relations'].setdefault(key,{'kind':kind,'count':0,'bytes':0,'samples':[],**({'from':from_,'to':to} if from_ else {})});rel['count']+=count;rel['bytes']+=bytes_
  if len(rel['samples'])<8:rel['samples'].append(sample)
 for group in d['duplicates']:
  byunit=collections.defaultdict(list)
  for path in group:
   r=records.get(path)
   if r and r['size']>0 and r['name']!='.DS_Store' and not r['name'].startswith('._') and '__MACOSX' not in PurePosixPath(path).parts:byunit[r['unit']].append(path)
  for a,b in itertools.combinations(sorted(byunit),2):
   pa=min(byunit[a],key=lambda p:(background(p),len(p),p));pb=min(byunit[b],key=lambda p:(background(p),len(p),p));r=records[pa];kind='background' if r['size']<=16 or background(pa) or background(pb) else 'duplicate'
   add(a,b,kind,{'a':pa,'b':pb,'size':r['size'],'sha256':r.get('sha256','')},bytes_=r['size']);stats[kind]+=1
 for ref in d.get('projectReferences',[]):
  a=ref['project'].split('/')[0];b=ref['asset'].split('/')[0]
  if ref['project'] not in records or ref['asset'] not in records:continue
  add(a,b,'dependency',{'a':ref['project'],'b':ref['asset'],'method':ref.get('kind','Premiere media reference')},from_=a,to=b)
 for z in d['zipMatches']:
  if z.get('verified'):add(z['zip'].split('/')[0],z['folder'].split('/')[0],'archive',{'a':z['zip'],'b':z['folder'],'files':z.get('files',0)},from_=z['zip'].split('/')[0],to=z['folder'].split('/')[0])
 for family,paths in d['fontFamilies'].items():
  byunit={}
  for path in paths:byunit.setdefault(path.split('/')[0],path)
  for a,b in itertools.combinations(sorted(byunit),2):add(a,b,'font',{'a':byunit[a],'b':byunit[b],'family':family})
 for group in d.get('projectTwins',[]):
  for a,b in itertools.combinations(sorted(group),2):add(a,b,'project-copy',{'a':a,'b':b})
 names=collections.defaultdict(list)
 for u in d['units']:
  n=re.sub(r'(?:[-_ ](?:copy|backup|old|v?\d+)|\s*\(\d+\))+$','',PurePosixPath(u['name']).stem.lower()).strip()
  if len(n)>=4:names[n].append(u['path'])
 for group in names.values():
  for a,b in itertools.combinations(group,2):add(a,b,'similar',{'a':a,'b':b})
 return {'version':1,'pairs':[dict(p,relations=list(p['relations'].values())) for p in pairs.values()],'stats':dict(stats),'scope':'Relationships within this scanned folder only. External projects and dynamic references may be missing.'}
