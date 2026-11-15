import json,sys,time,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path('app').resolve()))
from atlas_sources import Sources
class BootstrapTests(unittest.TestCase):
 def test_first_folder_is_scanned_not_mistaken_for_existing_placeholder(self):
  Path('work').mkdir(exist_ok=True)
  with tempfile.TemporaryDirectory(dir=Path('work').resolve()) as tmp:
   base=Path(tmp);root=base/'files';root.mkdir();(root/'note.txt').write_text('Synthetic test item');app=base/'runtime'/'app';app.mkdir(parents=True);(app/'atlas-template.html').write_text('__SNAPSHOT__ __THUMBNAILS__ __CONNECTION_DATA__')
   d=dict(bootstrap=True,root=str(root),units=[],records=[],scannedAt=time.time());sources=Sources(d,app);self.assertEqual(sources.snapshot()['sources'],[]);result=sources.start(str(root));self.assertIn('scan',result)
   for _ in range(500):
    job=next(iter(sources.scans.values()))
    if job['state']!='scanning':break
    time.sleep(.01)
   self.assertEqual(job['state'],'ready',job);self.assertEqual(sources.get(job['sourceId'])['manifest']['units'][0]['path'],'note.txt');self.assertTrue((root/'note.txt').is_file())
if __name__=='__main__':unittest.main()
