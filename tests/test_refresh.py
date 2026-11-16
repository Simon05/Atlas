import copy,http.client,json,shutil,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path('app').resolve()))
from atlas_sources import Sources
from atlas_scan import scan
from atlas_snapshots import snapshot_folder
from launch_organizer import make_server

class RefreshTests(unittest.TestCase):
 def setUp(self):
  Path('work').mkdir(exist_ok=True);self.temp=tempfile.TemporaryDirectory(dir=Path('work').resolve());self.base=Path(self.temp.name);self.home=self.base/'home';self.root=self.home/'Downloads';self.root.mkdir(parents=True);self.storage=self.base/'runtime'/'.atlas';self.storage.mkdir(parents=True);self.app=self.base/'runtime'/'app';self.app.mkdir();self.server=None
  self.home_patch=patch.object(Path,'home',return_value=self.home);self.home_patch.start();self.preview_patch=patch.dict(sys.modules,{'atlas_previews':SimpleNamespace(previews=lambda *args,**kwargs:{})});self.preview_patch.start()
  self.put('keep.txt','keep');self.put('change.txt','before');self.put('remove.txt','remove');self.old=scan(self.root);self.raw=json.dumps(self.old);(self.storage/'scan.json').write_text(self.raw);(self.storage/'Downloads Organizer.html').write_text('PREVIOUS PAGE');(self.app/'atlas-template.html').write_text('REFRESH PAGE __SNAPSHOT__ __THUMBNAILS__ __CONNECTION_DATA__');shutil.copyfile('app/apply_plan.py',self.app/'apply_plan.py');self.manager=Sources(self.old,self.storage,app_dir=self.app)
 def tearDown(self):
  if self.server:self.server.shutdown();self.server.server_close()
  for _ in range(500):
   if not any(j['state']=='scanning' for j in self.manager.scans.values()):break
   time.sleep(.01)
  self.preview_patch.stop();self.home_patch.stop();self.temp.cleanup()
 def put(self,name,text):
  p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);return p
 def wait(self):
  for _ in range(500):
   j=list(self.manager.scans.values())[-1]
   if j['state']!='scanning':return j
   time.sleep(.01)
  self.fail('Refresh timed out')
 def plan(self,context=None):
  d=(context or self.manager.get('downloads'))['manifest'];u=next(u for u in d['units'] if u['path']=='keep.txt');return dict(schemaVersion=1,sourceRoot=d['root'],destinationRoot=str(self.home/'Documents'/'Sorted'),scannedAt=d['scannedAt'],actions=[dict(source=u['path'],action='trash',fingerprint=u['fingerprint'],reviewed=False)])
 def wait_run(self,service,ident):
  for _ in range(500):
   j=next(j for j in service.snapshot()['jobs'] if j['id']==ident)
   if j['state'] not in {'verifying','applying','undoing'}:return j
   time.sleep(.01)
  self.fail('Verification timed out')
 def test_refresh_removes_missing_adds_new_and_preserves_previous_snapshot(self):
  old_context=self.manager.get('downloads');old_token=old_context['service'].token;old_runs=old_context['service'].runs
  (self.root/'remove.txt').unlink();self.put('change.txt','after');self.put('new.txt','new')
  self.manager.refresh('downloads');job=self.wait();self.assertEqual(job['state'],'ready',job);current=self.manager.get('downloads')
  self.assertEqual(current['id'],'downloads');self.assertEqual(current['service'].runs,old_runs);self.assertEqual(current['service'].token,old_token);self.assertEqual(snapshot_folder(self.storage),current['here']);self.assertEqual((self.storage/'scan.json').read_text(),self.raw);self.assertEqual((self.storage/'Downloads Organizer.html').read_text(),'PREVIOUS PAGE');self.assertEqual(job['summary'],dict(added=1,removed=1,changed=1,unchanged=1));self.assertEqual({u['path'] for u in current['manifest']['units']},{'keep.txt','change.txt','new.txt'});self.assertFalse((self.home/'.Trash').exists())
  restarted=Sources(self.old,self.storage,app_dir=self.app);self.assertEqual(restarted.get('downloads')['manifest']['scannedAt'],current['manifest']['scannedAt']);self.assertEqual(restarted.get('downloads')['here'],current['here'])
 def test_ready_runs_must_be_reverified_but_their_journals_survive(self):
  old_service=self.manager.get('downloads')['service'];old_plan=self.plan();j=old_service.verify(old_plan);self.assertEqual(self.wait_run(old_service,j['id'])['state'],'ready');log=old_service._folder(j['id'])/'undo-log.jsonl';log.write_text('');before=log.read_bytes()
  self.manager.refresh('downloads');self.assertEqual(self.wait()['state'],'ready');current=self.manager.get('downloads');service=current['service'];old_job=service.snapshot()['jobs'][0]
  self.assertFalse(old_job['snapshotCurrent']);self.assertFalse(old_job['canApply']);self.assertEqual(len(old_job['nextBatch']),1);self.assertEqual(log.read_bytes(),before);self.assertRaises(ValueError,service.operate,j['id'],'apply',old_job['reviewToken']);self.assertRaisesRegex(ValueError,'refreshed',service.verify,old_plan)
  fresh=service.verify(self.plan(current));self.assertEqual(self.wait_run(service,fresh['id'])['state'],'ready')
 def test_cancel_keeps_old_scan_and_releases_execution_gate(self):
  entered=threading.Event()
  def waiting(root,progress,cancelled,exclude):
   entered.set()
   while not cancelled():time.sleep(.005)
   raise ValueError('Scan cancelled. No files were changed.')
  old=self.manager.get('downloads')
  with patch('atlas_sources.scan',side_effect=waiting):
   result=self.manager.refresh('downloads');self.assertTrue(entered.wait(2));self.assertTrue(old['service'].refreshing);self.assertRaisesRegex(ValueError,'refreshing',old['service'].verify,self.plan());self.manager.stop(result['scan']['id']);self.assertEqual(self.wait()['state'],'cancelled')
  self.assertIs(self.manager.get('downloads'),old);self.assertFalse(old['service'].refreshing);self.assertEqual(snapshot_folder(self.storage),self.storage);self.assertEqual((self.storage/'scan.json').read_text(),self.raw)
 def test_failure_keeps_previous_page_and_allows_retry(self):
  with patch('atlas_sources.publish_snapshot',side_effect=OSError('Synthetic publish failure')):
   self.manager.refresh('downloads');self.assertEqual(self.wait()['state'],'failed')
  self.assertEqual(snapshot_folder(self.storage),self.storage);self.assertFalse(self.manager.get('downloads')['service'].refreshing);self.assertEqual((self.storage/'scan.json').read_text(),self.raw)
  self.manager.refresh('downloads');self.assertEqual(self.wait()['state'],'ready')
 def test_busy_operation_prevents_rescan(self):
  service=self.manager.get('downloads')['service']
  with patch.object(service,'snapshot',return_value={'busy':True}):self.assertRaisesRegex(ValueError,'operation',self.manager.refresh,'downloads')
  self.assertEqual(self.manager.scans,{});self.assertFalse(service.refreshing)
 def test_reused_filename_is_visible_without_losing_older_undo_history(self):
  service=self.manager.get('downloads')['service'];action=self.plan()['actions'][0];ident='a'*32;destination=self.home/'.Trash'/'keep.txt.old';destination.parent.mkdir();destination.write_text('keep');event=dict(event='intent',id='old-action',source=str(self.root/'keep.txt'),destination=str(destination),fingerprint=action['fingerprint'],action='trash');folder=service._folder(ident);folder.mkdir(parents=True);log=folder/'undo-log.jsonl';log.write_text(json.dumps(event)+'\n'+json.dumps(dict(event='done',id='old-action',source=event['source'],destination=event['destination'],fingerprint=event['fingerprint'],action='trash'))+'\n');service.jobs[ident]=dict(id=ident,createdAt=1,scannedAt=self.old['scannedAt'],state='completed',destinationRoot=str(self.home/'Documents'/'Sorted'),actions=[dict(action,warnings=[])],reviewToken='fixture');service._save(service.jobs[ident]);before=log.read_bytes()
  self.put('keep.txt','a different new file');self.manager.refresh('downloads');self.assertEqual(self.wait()['state'],'ready');new=self.manager.get('downloads')['service'];self.assertNotIn('keep.txt',new.applied_map());self.assertEqual(log.read_bytes(),before);self.assertTrue(new.snapshot()['jobs'][0]['canUndo']);self.assertEqual(destination.read_text(),'keep')
 def test_additional_source_keeps_identity_and_storage(self):
  other=self.home/'Documents';other.mkdir();(other/'note.txt').write_text('note');self.manager.start(str(other));job=self.wait();ident=job['sourceId'];old=self.manager.get(ident);(other/'note.txt').unlink();(other/'fresh.txt').write_text('fresh');self.manager.refresh(ident);self.assertEqual(self.wait()['state'],'ready');new=self.manager.get(ident);self.assertEqual(new['storage'],old['storage']);self.assertEqual(new['service'].runs,old['service'].runs);self.assertEqual(new['manifest']['sourceId'],ident)
  restarted=Sources(self.old,self.storage,app_dir=self.app);self.assertEqual(len(restarted.contexts),2);self.assertEqual(restarted.get(ident)['manifest']['units'][0]['path'],'fresh.txt')
 def test_unsafe_snapshot_pointer_is_refused(self):
  (self.storage/'current-snapshot.json').write_text('{"snapshot":"../../outside"}');self.assertRaises(ValueError,snapshot_folder,self.storage)
 def test_changed_or_missing_old_pending_actions_do_not_reappear(self):
  service=self.manager.get('downloads')['service'];plan=self.plan();u=next(u for u in self.old['units'] if u['path']=='remove.txt');plan['actions'].append(dict(source=u['path'],action='trash',fingerprint=u['fingerprint'],reviewed=False));j=service.verify(plan);self.assertEqual(self.wait_run(service,j['id'])['state'],'ready')
  (self.root/'remove.txt').unlink();self.put('keep.txt','replacement');self.manager.refresh('downloads');self.assertEqual(self.wait()['state'],'ready');self.assertEqual(self.manager.get('downloads')['service'].snapshot()['jobs'][0]['nextBatch'],[])
 def test_refresh_endpoint_preserves_source_token(self):
  self.server=make_server(0,self.old,self.storage,app_dir=self.app);self.manager=self.server.sources;threading.Thread(target=self.server.serve_forever,daemon=True).start();port=self.server.server_port
  def request(path,method='GET',body=None,token=None):
   headers={'Origin':f'http://127.0.0.1:{port}'}
   if token:headers['X-Atlas-Token']=token
   if body is not None:headers['Content-Type']='application/json';body=json.dumps(body)
   c=http.client.HTTPConnection('127.0.0.1',port);c.request(method,path,body,headers);r=c.getresponse();out=r.read();status=r.status;c.close();return status,out
  status,raw=request('/api/session');token=json.loads(raw)['token'];self.assertEqual(request('/api/refresh-source','POST',{})[0],403);self.assertEqual(request('/api/refresh-source','POST',{},token)[0],200);self.assertEqual(self.wait()['state'],'ready');status,raw=request('/api/session');self.assertEqual(json.loads(raw)['token'],token);self.assertIn(b'REFRESH PAGE',request('/')[1])

if __name__=='__main__':unittest.main()
