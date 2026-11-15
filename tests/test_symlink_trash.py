"""Regression proofs use only isolated files and a fixture Trash directory."""
import argparse, io, json, sys, tempfile, time, unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path('app').resolve()))
import apply_plan as engine
from atlas_scan import scan
from atlas_execution import Execution

class SymlinkTrashTests(unittest.TestCase):
 def setUp(self):
  Path('work').mkdir(exist_ok=True)
  self.tmp=tempfile.TemporaryDirectory(dir=Path('work').resolve());self.base=Path(self.tmp.name);self.home=self.base/'home';self.root=self.home/'Downloads';self.root.mkdir(parents=True);self.dest=self.home/'Documents'/'Sorted';self.here=self.base/'runtime';self.here.mkdir();self.external=self.base/'valuable.txt';self.external.write_text('DO NOT CHANGE');self.patcher=patch.object(Path,'home',return_value=self.home);self.patcher.start();self.service=None
 def tearDown(self):
  if self.service:
   for _ in range(500):
    if not self.service.snapshot()['busy']:break
    time.sleep(.01)
  self.patcher.stop();self.tmp.cleanup()
 def setup(self,top_link=False,broken=False,project=False):
  unit=self.root/('shortcut' if top_link else 'project')
  target=self.base/'missing' if broken else self.external
  if top_link:unit.symlink_to(target)
  else:
   unit.mkdir();(unit/'source.txt').write_text('inside file');(unit/'shortcut').symlink_to(target)
   if project:(unit/'package.json').write_text('{"name":"sample"}')
  d=scan(self.root);u=d['units'][0]
  def runner(j,mode,on_line):
   folder=self.service._folder(j['id']);args=argparse.Namespace(plan=str(folder/'plan.json'),log=str(folder/'undo-log.jsonl'),source_root=str(self.root),destination_root=str(self.dest),apply=mode!='verify',allow_project_actions=j['allowProjects'],allow_symlink_trash=j.get('allowSymlinkTrash',False),yes=True,batch_size=25,sources_file=str(folder/'selection.json') if mode=='apply' else None,only_action=None,undo=str(folder/'undo-log.jsonl'))
   capture=io.StringIO()
   try:
    with redirect_stdout(capture):engine.undo(args) if mode=='undo' else engine.run(args)
    rc=0
   except Exception as error:capture.write('STOPPED: '+str(error));rc=1
   for line in capture.getvalue().splitlines():on_line(line)
   return rc
  self.service=Execution(d,self.here,home=self.home,runner=runner)
  self.plan=dict(schemaVersion=1,sourceRoot=str(self.root),destinationRoot=str(self.dest),actions=[dict(source=u['path'],action='trash',destination=None,fingerprint=u['fingerprint'],reviewed=True,allowSymlinkTrash=True)])
  return unit
 def wait(self,job):
  for _ in range(500):
   current=next(j for j in self.service.snapshot()['jobs'] if j['id']==job['id'])
   if current['state'] not in {'verifying','applying','undoing'}:return current
   time.sleep(.01)
  self.fail('Timed out')
 def verify(self):return self.wait(self.service.verify(self.plan,True,True))
 def test_override_requires_both_explicit_flags_and_never_allows_move(self):
  self.setup();self.assertRaises(ValueError,self.service.verify,self.plan,True)
  self.plan['actions'][0]['allowSymlinkTrash']=False;self.assertRaises(ValueError,self.service.verify,self.plan,True,True)
  self.plan['actions'][0].update(allowSymlinkTrash=True,action='move',destination='Projects/project');self.assertRaises(ValueError,self.service.verify,self.plan,True,True)
 def test_project_still_requires_project_review(self):
  self.setup(project=True);self.assertRaises(ValueError,self.service.verify,self.plan,False,True)
  self.plan['actions'][0]['reviewed']=False;self.assertRaises(ValueError,self.service.verify,self.plan,True,True)
 def test_folder_trash_restore_without_reading_link_target(self):
  unit=self.setup(project=True)
  original=engine.digest
  def guarded(path):
   self.assertNotEqual(path,self.external);self.assertNotEqual(path.name,'shortcut');return original(path)
  with patch.object(engine,'digest',side_effect=guarded):
   j=self.verify();self.assertEqual(j['state'],'ready',j.get('error'));j=self.wait(self.service.operate(j['id'],'apply',j['reviewToken']));self.assertEqual(j['state'],'completed',j.get('error'));self.assertFalse(unit.exists());self.assertEqual(self.external.read_text(),'DO NOT CHANGE');j=self.wait(self.service.operate(j['id'],'undo',j['reviewToken']));self.assertEqual(j['state'],'restored',j.get('error'))
  self.assertTrue((unit/'shortcut').is_symlink());self.assertEqual(self.external.read_text(),'DO NOT CHANGE')
 def test_directory_link_is_not_walked_or_hashed(self):
  unit=self.setup();vault=self.base/'vault';vault.mkdir();(vault/'private.txt').write_text('external directory contents');(unit/'shortcut').unlink();(unit/'shortcut').symlink_to(vault,target_is_directory=True)
  original=engine.digest
  def guarded(path):
   self.assertNotIn(vault,path.parents);return original(path)
  with patch.object(engine,'digest',side_effect=guarded):
   j=self.verify();self.assertEqual(j['state'],'ready',j.get('error'));j=self.wait(self.service.operate(j['id'],'apply',j['reviewToken']));self.assertEqual(j['state'],'completed',j.get('error'))
  self.assertEqual((vault/'private.txt').read_text(),'external directory contents')
 def test_broken_top_level_link_trash_restore_and_crash_recovery(self):
  unit=self.setup(top_link=True,broken=True);j=self.verify();self.assertEqual(j['state'],'ready',j.get('error'));j=self.wait(self.service.operate(j['id'],'apply',j['reviewToken']));self.assertEqual(j['appliedCount'],1,j.get('error'))
  log=self.service._folder(j['id'])/'undo-log.jsonl';lines=[line for line in log.read_text().splitlines() if json.loads(line)['event']!='done'];log.write_text('\n'.join(lines)+'\n');self.assertEqual(len(self.service._applied(self.service.jobs[j['id']])),1)
  j=self.wait(self.service.operate(j['id'],'undo',j['reviewToken']));self.assertEqual(j['state'],'restored',j.get('error'));self.assertTrue(unit.is_symlink());self.assertFalse(unit.exists())
 def test_retarget_after_verification_refused(self):
  unit=self.setup();j=self.verify();(unit/'shortcut').unlink();(unit/'shortcut').symlink_to(self.base/'another-target');j=self.wait(self.service.operate(j['id'],'apply',j['reviewToken']));self.assertEqual(j['state'],'failed');self.assertIn('Symbolic links changed',j['error']);self.assertTrue(unit.exists());self.assertFalse((self.home/'.Trash').exists())
 def test_retarget_before_undo_refused(self):
  self.setup(top_link=True);j=self.verify();j=self.wait(self.service.operate(j['id'],'apply',j['reviewToken']));path=Path(self.service.applied_map()['shortcut']['destination']);path.unlink();path.symlink_to(self.base/'different');j=self.wait(self.service.operate(j['id'],'undo',j['reviewToken']));self.assertEqual(j['state'],'failed');self.assertFalse(engine.present(self.root/'shortcut'));self.assertEqual(self.external.read_text(),'DO NOT CHANGE')
 def test_incomplete_scan_cannot_be_overridden(self):
  self.setup();self.service.units['project']['hashComplete']=False;self.assertRaises(ValueError,self.service.verify,self.plan,True,True)
 def test_missing_items_reported_together_without_touching_remaining_files(self):
  unit=self.setup();(unit/'shortcut').unlink();d=scan(self.root)
  for name in ['gone-one.txt','gone-two.txt','keep.txt']:(self.root/name).write_text(name)
  d=scan(self.root);self.service=Execution(d,self.here,home=self.home)
  actions=[dict(source=u['path'],action='trash',fingerprint=u['fingerprint'],reviewed=True) for u in d['units']]
  self.plan['actions']=actions
  for name in ['gone-one.txt','gone-two.txt']:(self.root/name).unlink()
  j=self.wait(self.service.verify(self.plan,True));self.assertEqual(j['state'],'failed');self.assertEqual({i['source'] for i in j['issues']},{'gone-one.txt','gone-two.txt'});self.assertTrue((self.root/'keep.txt').exists());self.assertFalse((self.home/'.Trash').exists())
 def test_cli_requires_override_switch(self):
  self.setup();canonical=self.service.canonical(self.plan,True,True);p=self.base/'plan.json';p.write_text(json.dumps(canonical));args=argparse.Namespace(plan=str(p),source_root=str(self.root),destination_root=str(self.dest),log=str(self.base/'log.jsonl'),apply=True,allow_project_actions=True,yes=True,batch_size=25)
  self.assertRaises(ValueError,engine.run,args)

if __name__=='__main__':unittest.main()
