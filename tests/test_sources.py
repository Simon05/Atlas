import sys,json,tempfile,time,unittest,threading,http.client,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path('app').resolve()))
from atlas_scan import scan
from atlas_sources import Sources
from atlas_execution import Execution
from launch_organizer import make_server
import apply_plan as engine
class SourceTests(unittest.TestCase):
 def setUp(self):
  Path('work').mkdir(exist_ok=True)
  self.tmp=tempfile.TemporaryDirectory(dir=str(Path('work').resolve()));self.base=Path(self.tmp.name);self.root=self.base/'Documents';self.root.mkdir();self.here=self.base/'runtime'/'app';self.here.mkdir(parents=True);self.server=None
 def tearDown(self):
  if self.server:self.server.shutdown();self.server.server_close()
  self.tmp.cleanup()
 def put(self,path,text):
  p=self.root/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p
 def sample(self):
  for name in ['website','website-copy']:
   self.put(name+'/package.json',json.dumps({'name':'demo','dependencies':{'shared':'file:../shared'}}));self.put(name+'/src/app.ts',"import icon from '../../shared/icon.svg'; import foo from './used';");self.put(name+'/src/used.ts','export default 42');self.put(name+'/unused.png','unused image');self.put(name+'/node_modules/pkg/file.js','generated');self.put(name+'/.env','SECRET_VALUE_DO_NOT_ANALYZE');self.put(name+'/.git/config','git fixture')
  self.put('shared/package.json','{"name":"shared"}');self.put('shared/icon.svg','<svg/>');self.put('old-export/render.png','leftover');self.put('loose.txt','duplicate bytes');self.put('loose-copy.txt','duplicate bytes')
  with zipfile.ZipFile(self.root/'old-export.zip','w') as z:z.write(self.root/'old-export/render.png','render.png')
  return scan(self.root)
 def test_analysis_keeps_units_and_evidence(self):
  d=self.sample();u={u['path']:u for u in d['units']};self.assertTrue(u['website']['locked']);self.assertEqual(u['website']['fingerprint'],engine.fingerprint(self.root/'website')[0]);self.assertEqual(d['projectTwins'],[['website','website-copy']]);self.assertTrue(any(r['kind']=='Project local dependency' for r in d['projectReferences']));self.assertTrue(any(r['asset']=='shared/icon.svg' for r in d['projectReferences']));self.assertEqual(u['shared']['suggestion'],'Keep');self.assertTrue(any('Known project' in w for w in u['shared']['warnings']));self.assertTrue(any(f['kind']=='leftover' and f['unit']=='old-export' and f['confidence']=='Low' for f in d['projectFindings']));self.assertTrue(any(f['kind']=='unreferenced' and f['unit']=='website' for f in d['projectFindings']));self.assertTrue(any(f['kind']=='generated' for f in d['projectFindings']));self.assertEqual(len(d['zipMatches']),1);self.assertNotIn('SECRET_VALUE_DO_NOT_ANALYZE',json.dumps(d));self.assertFalse((self.base/'.Trash').exists())
 def test_root_project_cannot_split(self):
  self.put('package.json','{"name":"root"}');self.put('src/app.ts','export default 1');d=scan(self.root);self.assertTrue(d['rootProject']);self.assertTrue(all(u['locked'] and u['suggestion']=='Keep' for u in d['units']));service=Execution(d,self.here);self.assertRaisesRegex(ValueError,'itself a project',service.canonical,{},True)
 def test_excluded_runtime_is_incomplete(self):
  runtime=self.root/'Codex'/'Atlas';runtime.mkdir(parents=True);(runtime/'private.txt').write_text('not inventoried');self.put('Codex/keep.txt','visible');d=scan(self.root,exclude=[runtime]);u=next(u for u in d['units'] if u['path']=='Codex');self.assertFalse(u['hashComplete']);self.assertEqual(u['suggestion'],'Keep');self.assertNotIn('Codex/Atlas/private.txt',{r['path'] for r in d['records']})
 def test_cancellation_has_no_source_writes(self):
  self.put('keep.txt','test');self.assertRaises(ValueError,scan,self.root,cancelled=lambda:True);self.assertEqual([p.name for p in self.root.iterdir()],['keep.txt'])
 def manager(self):
  download=self.base/'Downloads';download.mkdir();(download/'saved.txt').write_text('my Downloads plan');d=scan(download);(self.here/'scan.json').write_text(json.dumps(d));(self.here/'Downloads Organizer.html').write_text('DOWNLOADS PAGE');(self.here/'atlas-template.html').write_text('SOURCE PAGE __SNAPSHOT__ __THUMBNAILS__');return Sources(d,self.here)
 def wait(self,m):
  for _ in range(500):
   job=list(m.scans.values())[-1]
   if job['state']!='scanning':return job
   time.sleep(.02)
  self.fail('scan timed out')
 def test_scan_publish_restart_isolation(self):
  self.put('new.txt','new folder');m=self.manager();before=(self.here/'scan.json').read_bytes();result=m.start(str(self.root));j=self.wait(m);self.assertEqual(j['state'],'ready',j);c=m.get(j['sourceId']);self.assertNotEqual(c['service'].runs,m.get('downloads')['service'].runs);self.assertEqual(c['service'].engine_path,self.here/'apply_plan.py');self.assertEqual((self.here/'scan.json').read_bytes(),before);self.assertEqual(c['manifest']['root'],str(self.root));self.assertEqual(m.start(str(self.root)),{'existing':j['sourceId']});self.assertEqual(len(Sources(m.get('downloads')['manifest'],self.here).contexts),2);self.assertRaises(ValueError,m.start,str(self.root/'subfolder'));self.assertEqual(len(list(self.root.iterdir())),1)
 def test_new_source_verification_uses_shared_engine_and_private_run(self):
  import shutil
  self.put('new.txt','new folder');m=self.manager();shutil.copyfile('app/apply_plan.py',self.here/'apply_plan.py');m.start(str(self.root));j=self.wait(m);c=m.get(j['sourceId']);u=c['manifest']['units'][0];plan=dict(schemaVersion=1,sourceRoot=str(self.root),destinationRoot=str(Path.home()/'Desktop'/'Atlas Test Destination'),actions=[dict(source=u['path'],action='trash',fingerprint=u['fingerprint'],reviewed=False)])
  job=c['service'].verify(plan)
  for _ in range(300):
   current=c['service'].snapshot()['jobs'][0]
   if current['state']!='verifying':break
   time.sleep(.01)
  self.assertEqual(current['state'],'ready',current);self.assertEqual(m.get('downloads')['service'].snapshot()['jobs'],[]);self.assertTrue((self.root/'new.txt').is_file());self.assertEqual(c['service']._folder(job['id']).parent,c['here']/'runs')
 def test_python_and_git_project_units(self):
  self.put('python-project/pyproject.toml','[project]');self.put('python-project/main.py','print("sample")');self.put('git-project/.git/config','[core]');self.put('git-project/main.py','print("sample")');d=scan(self.root);self.assertTrue(all(u['locked'] for u in d['units']));self.assertFalse(d['rootProject'])
 def test_alias_links_and_symlink_inventory(self):
  self.put('app/package.json','{"name":"app"}');self.put('app/tsconfig.json','{"compilerOptions":{"baseUrl":".","paths":{"@/*":["src/*"]}}}');self.put('app/src/app.ts',"import x from '@/helper';");self.put('app/src/helper.ts','export default 1');(self.root/'outside-link').symlink_to(self.base);d=scan(self.root);self.assertTrue(any(r['asset']=='app/src/helper.ts' for r in d['projectReferences']));self.assertEqual(next(u for u in d['units'] if u['path']=='outside-link')['kind'],'link');self.assertFalse(any(r['path'].startswith('outside-link/') for r in d['records']))
 def test_native_picker_cancel_and_path(self):
  from types import SimpleNamespace
  m=self.manager()
  with patch('atlas_sources.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=str(self.root)+'\n',stderr='')):self.assertEqual(m.choose(),{'path':str(self.root)})
  with patch('atlas_sources.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout='',stderr='(-128)')):self.assertEqual(m.choose(),{'cancelled':True})
  self.assertRaises(ValueError,m.validate,str(Path.home()));self.assertRaises(ValueError,m.validate,str(self.here));self.assertRaises(ValueError,m.validate,'/System')
 def test_source_http_identity_and_media(self):
  self.put('secret.txt','ONLY IN NEW SOURCE');m=self.manager();m.start(str(self.root));j=self.wait(m);self.assertEqual(j['state'],'ready');ident=j['sourceId'];self.server=make_server(0,m.get('downloads')['manifest'],self.here);port=self.server.server_port;threading.Thread(target=self.server.serve_forever,daemon=True).start()
  def request(path,token=None,method='GET',body=None):
   conn=http.client.HTTPConnection('127.0.0.1',port);headers={'Origin':f'http://127.0.0.1:{port}'}
   if token:headers['X-Atlas-Token']=token
   if body is not None:headers['Content-Type']='application/json';body=json.dumps(body)
   conn.request(method,path,body,headers);r=conn.getresponse();data=r.read();status=r.status;conn.close();return status,data
  status,b=request('/api/session');old=json.loads(b);status,b=request('/api/session?source='+ident);new=json.loads(b);self.assertNotEqual(old['token'],new['token']);self.assertEqual(new['sourceId'],ident);self.assertEqual(request('/api/state?source='+ident,old['token'])[0],403);self.assertEqual(request('/api/state?source='+ident,new['token'])[0],200);self.assertEqual(request('/media?path=secret.txt')[0],404);self.assertEqual(request('/media?path=secret.txt&source='+ident)[1],b'ONLY IN NEW SOURCE');self.assertEqual(request('/?source=bogus')[0],404);self.assertIn(b'SOURCE PAGE',request('/?source='+ident)[1]);self.assertEqual(request('/api/verify?source='+ident,old['token'],'POST',{'plan':{}})[0],403)
if __name__=='__main__':unittest.main()
