import sys,json,io,time,tempfile,unittest,argparse,threading,http.client
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch
sys.path.insert(0,str(Path('app').resolve()))
import apply_plan as engine
from atlas_execution import Execution
from launch_organizer import make_server
class ExecutionTests(unittest.TestCase):
 def setUp(self):
  Path('work').mkdir(exist_ok=True)
  self.tmp=tempfile.TemporaryDirectory(dir=str(Path('work').resolve()));self.base=Path(self.tmp.name);self.home=self.base/'home';self.root=self.home/'Downloads';self.root.mkdir(parents=True);self.dest=self.home/'Documents'/'Sorted';self.here=self.base/'app';self.here.mkdir();self.homepatch=patch.object(Path,'home',return_value=self.home);self.homepatch.start();self.server=None;self.services=[]
 def tearDown(self):
  if self.server:self.server.shutdown();self.server.server_close()
  for service in self.services:
   for _ in range(500):
    if not service.snapshot()['busy']:break
    time.sleep(.01)
  self.homepatch.stop();self.tmp.cleanup()
 def setup_plan(self,n=2,project=False):
  units=[];actions=[]
  for i in range(n):
   name=('source.psd' if project else f'file-{i:03}.txt');p=self.root/name;p.write_text('safe fixture '+str(i));fp,locked=engine.fingerprint(p);u=dict(path=name,name=name,kind='file',bytes=p.stat().st_size,fingerprint=fp,hashComplete=True,locked=locked,warnings=['Project unit: review linked assets'] if locked else []);units.append(u);actions.append(dict(source=name,action='trash' if i%2==0 and not project else 'move',destination=None if i%2==0 and not project else 'Files/'+name,fingerprint=fp,reviewed=project))
  manifest=dict(root=str(self.root),units=units,records=[dict(path=u['path'],kind='file') for u in units],scannedAt=time.time());plan=dict(schemaVersion=1,sourceRoot=str(self.root),destinationRoot=str(self.dest),actions=actions)
  def runner(j,mode,on_line):
   folder=self.service._folder(j['id']);args=argparse.Namespace(plan=str(folder/'plan.json'),source_root=str(self.root),destination_root=str(self.dest),log=str(folder/'undo-log.jsonl'),apply=mode!='verify',allow_project_actions=j['allowProjects'],allow_symlink_trash=j.get('allowSymlinkTrash',False),yes=True,batch_size=25,max_actions=None,sources_file=str(folder/'selection.json') if mode=='apply' else None,only_action=j.get('activeScope') if j.get('activeScope') in ('trash','move') else None,undo=str(folder/'undo-log.jsonl') if mode=='undo' else None)
   capture=io.StringIO()
   try:
    with redirect_stdout(capture):engine.undo(args) if mode=='undo' else engine.run(args)
    rc=0
   except Exception as e:capture.write('STOPPED: '+str(e)+'\n');rc=1
   for line in capture.getvalue().splitlines():on_line(line)
   return rc
  self.service=Execution(manifest,self.here,home=self.home,runner=runner);self.services.append(self.service);return plan
 def wait(self,j):
  for _ in range(500):
   v=next(v for v in self.service.snapshot()['jobs'] if v['id']==j['id'])
   if v['state'] not in {'verifying','applying','undoing'}:return v
   time.sleep(.01)
  self.fail('job timed out')
 def test_verify_has_no_file_effects(self):
  p=self.setup_plan();j=self.wait(self.service.verify(p));self.assertEqual(j['state'],'ready');self.assertEqual(len(list(self.root.iterdir())),2);self.assertFalse((self.home/'.Trash').exists());self.assertFalse(self.dest.exists());self.assertEqual(self.service.snapshot()['applied'],{})
 def test_apply_all_then_restore(self):
  p=self.setup_plan(27);j=self.wait(self.service.verify(p));token=j['reviewToken'];self.assertEqual(len(j['nextBatch']),27)
  self.assertNotIn('--max-actions',self.service.command(self.service.jobs[j['id']],'apply'))
  j=self.wait(self.service.operate(j['id'],'apply',token));self.assertEqual((j['state'],j['appliedCount']),('completed',27));self.assertEqual(len(list(self.root.iterdir())),0);self.assertRaises(ValueError,self.service.operate,j['id'],'apply',token)
  restarted=Execution(self.service.manifest,self.here,home=self.home,runner=self.service.runner);self.assertEqual(len(restarted.snapshot()['applied']),27)
  self.assertEqual(len(j['restoreBatch']),27);j=self.wait(self.service.operate(j['id'],'undo',j['reviewToken']));self.assertEqual((j['state'],j['appliedCount']),('restored',0));self.assertEqual(len(list(self.root.iterdir())),27);self.assertEqual(self.service.snapshot()['applied'],{})
 def test_changed_source_stops_before_apply(self):
  p=self.setup_plan();j=self.wait(self.service.verify(p));(self.root/'file-000.txt').write_text('CHANGED');j=self.wait(self.service.operate(j['id'],'apply',j['reviewToken']));self.assertEqual(j['state'],'failed');self.assertEqual(j['appliedCount'],0);self.assertIn('changed',j['error']);self.assertFalse((self.home/'.Trash').exists())
 def test_root_and_fingerprint_forgery(self):
  p=self.setup_plan();p['destinationRoot']=str(self.home/'Outside');self.assertRaises(ValueError,self.service.verify,p);p['destinationRoot']=str(self.dest);p['actions'][0]['fingerprint']='forged';self.assertRaises(ValueError,self.service.verify,p);self.assertEqual(self.service.jobs,{})
 def test_unscanned_source_rejected(self):
  p=self.setup_plan();p['actions'][0]['source']='../outside';self.assertRaises(ValueError,self.service.verify,p)
 def test_project_requires_both_reviews(self):
  p=self.setup_plan(1,True);self.assertRaises(ValueError,self.service.verify,p);p['actions'][0]['reviewed']=False;self.assertRaises(ValueError,self.service.verify,p,True);p['actions'][0]['reviewed']=True;j=self.wait(self.service.verify(p,True));self.assertEqual(j['state'],'ready')
 def test_saved_plan_tampering(self):
  p=self.setup_plan();j=self.wait(self.service.verify(p));path=self.service._folder(j['id'])/'plan.json';data=json.loads(path.read_text());data['actions'][0]['source']='other';path.write_text(json.dumps(data));self.assertRaises(ValueError,self.service.operate,j['id'],'apply',j['reviewToken'])
 def test_busy_rejects_duplicate_operations(self):
  p=self.setup_plan();j=self.wait(self.service.verify(p));self.service.jobs[j['id']]['state']='applying';self.assertRaises(ValueError,self.service.verify,p);self.service.jobs[j['id']]['state']='ready'
 def test_only_trash_scope(self):
  p=self.setup_plan(28);p['actions']=[a for a in p['actions'] if a['action']=='trash'];j=self.wait(self.service.verify(p));j=self.wait(self.service.operate(j['id'],'apply',j['reviewToken']));self.assertEqual(j['appliedCount'],14);self.assertTrue(all(p.name.endswith('.txt') for p in self.root.iterdir()));self.assertEqual(len(list(self.root.iterdir())),14)
 def test_only_move_scope(self):
  p=self.setup_plan(28);p['actions']=[a for a in p['actions'] if a['action']=='move'];j=self.wait(self.service.verify(p));j=self.wait(self.service.operate(j['id'],'apply',j['reviewToken']));self.assertEqual(j['appliedCount'],14);self.assertEqual(len(list(self.root.iterdir())),14);self.assertFalse((self.home/'.Trash').exists())
 def test_old_paused_run_continues_without_limit(self):
  p=self.setup_plan(55);j=self.wait(self.service.verify(p));folder=self.service._folder(j['id']);args=argparse.Namespace(plan=str(folder/'plan.json'),source_root=str(self.root),destination_root=str(self.dest),log=str(folder/'undo-log.jsonl'),apply=True,allow_project_actions=False,yes=True,batch_size=25,max_actions=25,undo=None)
  with redirect_stdout(io.StringIO()):engine.run(args)
  self.service.jobs[j['id']]['state']='paused';self.service._save(self.service.jobs[j['id']]);restarted=Execution(self.service.manifest,self.here,home=self.home,runner=self.service.runner);self.service=restarted;self.services.append(restarted);current=restarted.snapshot()['jobs'][0];self.assertEqual(current['appliedCount'],25);self.assertEqual(len(current['nextBatch']),30);current=self.wait(restarted.operate(current['id'],'apply',current['reviewToken']));self.assertEqual((current['state'],current['appliedCount']),('completed',55))
 def test_scope_switch_with_same_run_and_log(self):
  p=self.setup_plan(30);j=self.wait(self.service.verify(p));j=self.wait(self.service.operate(j['id'],'apply',j['reviewToken'],'trash'));self.assertEqual((j['state'],j['appliedCount']),('paused',15));self.assertEqual(len(j['nextBatch']),15);self.assertTrue(all(a['action']=='move' for a in j['nextBatch']));j=self.wait(self.service.operate(j['id'],'apply',j['reviewToken'],'move'));self.assertEqual((j['state'],j['appliedCount']),('completed',30));j=self.wait(self.service.operate(j['id'],'undo',j['reviewToken']));self.assertEqual(j['state'],'restored');self.assertEqual(len(list(self.root.iterdir())),30)
 def test_overlapping_runs_exclude_completed_sources(self):
  p=self.setup_plan(30);first=self.wait(self.service.verify(p));subset=dict(p,actions=p['actions'][:14]);second=self.wait(self.service.verify(subset));second=self.wait(self.service.operate(second['id'],'apply',second['reviewToken']));self.assertEqual(second['appliedCount'],14)
  current=next(j for j in self.service.snapshot()['jobs'] if j['id']==first['id']);self.assertEqual(len(current['nextBatch']),16);self.assertEqual(current['completedElsewhere'],14);current=self.wait(self.service.operate(current['id'],'apply',current['reviewToken']));self.assertEqual((current['state'],current['appliedCount']),('completed',16));self.assertEqual(len(list(self.root.iterdir())),0)
 def copy_pair_plan(self):
  plan=self.setup_plan(2);(self.root/'file-001.txt').write_text((self.root/'file-000.txt').read_text())
  for u in self.service.units.values():u['fingerprint']=engine.fingerprint(self.root/u['path'])[0]
  self.service.units['file-000.txt']['duplicateKeeper']='file-001.txt'
  for a in plan['actions']:a.update(action='trash',destination=None,fingerprint=self.service.units[a['source']]['fingerprint'])
  return plan
 def test_explicit_both_copy_trash_and_restore(self):
  p=self.copy_pair_plan();p['actions'][0].update(discardRetained=True,reviewedCopies=['file-001.txt']);j=self.wait(self.service.verify(p));self.assertEqual(j['state'],'ready');j=self.wait(self.service.operate(j['id'],'apply',j['reviewToken']));self.assertEqual((j['state'],j['appliedCount']),('completed',2));j=self.wait(self.service.operate(j['id'],'undo',j['reviewToken']));self.assertEqual(j['state'],'restored');self.assertEqual(len(list(self.root.iterdir())),2)
 def test_unacknowledged_both_copy_trash_refused(self):
  p=self.copy_pair_plan();j=self.wait(self.service.verify(p));self.assertEqual(j['state'],'failed');self.assertEqual(len(list(self.root.iterdir())),2)
 def test_incomplete_copy_acknowledgement_refused(self):
  p=self.copy_pair_plan();p['actions'][0].update(discardRetained=True,reviewedCopies=[]);self.assertRaises(ValueError,self.service.verify,p)
 def test_reveal_resolves_applied_location(self):
  p=self.setup_plan();self.assertEqual(self.service.reveal_path('file-000.txt'),self.root/'file-000.txt');self.assertRaises(ValueError,self.service.reveal_path,'../private.txt');j=self.wait(self.service.verify(p));j=self.wait(self.service.operate(j['id'],'apply',j['reviewToken']));path=self.service.reveal_path('file-000.txt');self.assertEqual(path.parent,self.home/'.Trash')
  with patch('atlas_execution.subprocess.run') as run:
   self.service.reveal('file-000.txt');self.assertEqual(run.call_args[0][0],['/usr/bin/open','-R',str(path)])
 def test_native_destination_chooser_validation(self):
  self.setup_plan();self.dest.mkdir(parents=True)
  from types import SimpleNamespace
  with patch('atlas_execution.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=str(self.dest)+'\n',stderr='')):
   self.assertEqual(self.service.choose_destination(),{'path':str(self.dest)})
  with patch('atlas_execution.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=str(self.home)+'\n',stderr='')):
   self.assertRaises(ValueError,self.service.choose_destination)
  with patch('atlas_execution.subprocess.run',return_value=SimpleNamespace(returncode=1,stdout='',stderr='User canceled. (-128)')):
   self.assertEqual(self.service.choose_destination(),{'cancelled':True})
 def test_http_origin_token_and_confirmation(self):
  p=self.setup_plan();self.server=make_server(0,self.service.manifest,self.here,self.service);threading.Thread(target=self.server.serve_forever,daemon=True).start();port=self.server.server_port;host=f'127.0.0.1:{port}'
  def req(method,path,body=None,headers=None):
   con=http.client.HTTPConnection('127.0.0.1',port);con.request(method,path,None if body is None else json.dumps(body),headers=headers or {});r=con.getresponse();data=r.read();code=r.status;con.close();return code,data
  code,raw=req('GET','/api/session');self.assertEqual(code,200);token=json.loads(raw)['token'];base={'Content-Type':'application/json','Origin':'http://'+host,'X-Atlas-Token':token}
  for headers in [dict(base,Origin='https://evil.example'),dict(base,**{'X-Atlas-Token':'bad'}),{'Content-Type':'application/json','X-Atlas-Token':token}]:self.assertEqual(req('POST','/api/verify',{'plan':p},headers)[0],403)
  self.assertEqual(req('GET','/api/state')[0],403);self.assertEqual(req('OPTIONS','/api/apply')[0],403)
  code,raw=req('POST','/api/verify',{'plan':p},base);self.assertEqual(code,200);j=self.wait(json.loads(raw)['job']);self.assertEqual(j['state'],'ready');self.assertEqual(req('POST','/api/apply',{'jobId':j['id'],'reviewToken':j['reviewToken']},base)[0],400);self.assertEqual(len(list(self.root.iterdir())),2)
if __name__=='__main__':unittest.main()
