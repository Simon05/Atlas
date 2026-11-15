import importlib.util,sys,tempfile,json,argparse,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('ap','app/apply_plan.py');ap=importlib.util.module_from_spec(spec);spec.loader.exec_module(ap)
class Safety(unittest.TestCase):
 def setUp(self):
  Path('work').mkdir(exist_ok=True)
  self.temp=tempfile.TemporaryDirectory(dir=str(Path('work').resolve()));self.base=Path(self.temp.name);self.root=self.base/'Downloads';self.dest=self.base/'Organized';self.root.mkdir();self.log=self.base/'journal.jsonl';self.homepatch=patch.object(Path,'home',return_value=self.base);self.homepatch.start()
 def tearDown(self):self.homepatch.stop();self.temp.cleanup()
 def item(self,name='a.txt',text='hello',action='move'):
  p=self.root/name;p.write_text(text);return dict(source=name,action=action,destination='Docs/'+name if action=='move' else None,fingerprint=ap.fingerprint(p)[0],hashComplete=True,reviewed=True,warnings=[],retain=[])
 def args(self,actions,apply=False):
  p=self.base/'plan.json';p.write_text(json.dumps(dict(schemaVersion=1,sourceRoot=str(self.root),destinationRoot=str(self.dest),actions=actions)));return argparse.Namespace(plan=str(p),source_root=str(self.root),destination_root=str(self.dest),log=str(self.log),apply=apply,allow_project_actions=False,yes=True,batch_size=2,undo=None)
 def test_dry_run(self):
  a=self.args([self.item()]);ap.run(a);self.assertTrue((self.root/'a.txt').exists());self.assertFalse(self.log.exists());self.assertFalse(self.dest.exists())
 def test_move_resume_undo(self):
  a=self.args([self.item()],True);ap.run(a);self.assertTrue((self.dest/'Docs/a.txt').exists());ap.run(a);a.undo=str(self.log);ap.undo(a);self.assertTrue((self.root/'a.txt').exists())
 def test_trash_and_undo(self):
  a=self.args([self.item(action='trash')],True);ap.run(a);self.assertFalse((self.root/'a.txt').exists());self.assertEqual(len(list((self.base/'.Trash').iterdir())),1);a.undo=str(self.log);ap.undo(a);self.assertTrue((self.root/'a.txt').exists())
 def test_change_refused(self):
  item=self.item();a=self.args([item],True);(self.root/'a.txt').write_text('changed');self.assertRaises(ValueError,ap.run,a);self.assertFalse(self.log.exists())
 def test_collision_refused(self):
  a=self.args([self.item()],True);(self.dest/'Docs').mkdir(parents=True);(self.dest/'Docs/a.txt').write_text('other');self.assertRaises(ValueError,ap.run,a);self.assertTrue((self.root/'a.txt').exists())
 def test_traversal_refused(self):
  item=self.item();item['destination']='../escape';a=self.args([item],True);self.assertRaises(ValueError,ap.run,a)
 def test_project_guard(self):
  a=self.args([self.item('source.psd')],True);self.assertRaises(ValueError,ap.run,a);a.allow_project_actions=True;ap.run(a);self.assertTrue((self.dest/'Docs/source.psd').exists())
 def test_symlink_guard(self):
  a=self.args([self.item()],True);(self.root/'a.txt').rename(self.base/'real');(self.root/'a.txt').symlink_to(self.base/'real');self.assertRaises(ValueError,ap.run,a)
 def test_undo_changed_refused(self):
  a=self.args([self.item()],True);ap.run(a);(self.dest/'Docs/a.txt').write_text('changed');a.undo=str(self.log);self.assertRaises(ValueError,ap.undo,a)
 def test_pending_undo(self):
  item=self.item();a=self.args([item],True);dst=self.dest/'Docs/a.txt';dst.parent.mkdir(parents=True);ap.append(self.log,dict(event='intent',id='pending',source=str(self.root/'a.txt'),destination=str(dst),fingerprint=item['fingerprint']));ap.rename_exclusive(self.root/'a.txt',dst);a.undo=str(self.log);ap.undo(a);self.assertTrue((self.root/'a.txt').exists())
 def test_retained_changed(self):
  keep=self.item('keep.txt');dup=self.item('dup.txt',action='trash');dup['retain']=['keep.txt'];dup['retainFingerprints']={'keep.txt':keep['fingerprint']};(self.root/'keep.txt').write_text('changed');a=self.args([dup],True);self.assertRaises(ValueError,ap.run,a)
 def test_atomic_no_overwrite(self):
  a=self.root/'a';b=self.root/'b';a.write_text('a');b.write_text('b');self.assertRaises(FileExistsError,ap.rename_exclusive,a,b);self.assertEqual(b.read_text(),'b')
if __name__=='__main__':unittest.main()
