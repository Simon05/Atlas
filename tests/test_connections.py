import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path('app').resolve()))
from atlas_relations import build_relations
class RelationTests(unittest.TestCase):
 def manifest(self):
  paths=['App/src/main.ts','App/logo.svg','App/node_modules/react/index.js','Other/logo.svg','Other/node_modules/react/index.js','Other/.git/hooks/pre-commit.sample','App/.git/hooks/pre-commit.sample','Archive.zip']
  records=[dict(path=p,name=p.split('/')[-1],unit=p.split('/')[0],kind='file',size=42,sha256='ab'*32) for p in paths]
  return dict(units=[dict(path=p,name=p) for p in ['App','Other','Archive.zip']],records=records,duplicates=[['App/logo.svg','Other/logo.svg'],['App/node_modules/react/index.js','Other/node_modules/react/index.js'],['App/.git/hooks/pre-commit.sample','Other/.git/hooks/pre-commit.sample']],projectReferences=[dict(project='App/src/main.ts',asset='Other/logo.svg',kind='Project import / asset')],zipMatches=[dict(zip='Archive.zip',folder='App',verified=True,files=4)],fontFamilies={},projectTwins=[])
 def test_matches_are_distinct_from_dependencies(self):
  d=self.manifest();index=build_relations(d);pair=next(p for p in index['pairs'] if set([p['a'],p['b']])=={'App','Other'});r={r['kind']:r for r in pair['relations']};self.assertEqual(r['duplicate']['count'],1);self.assertEqual(r['background']['count'],2);self.assertEqual(r['dependency']['from'],'App');self.assertEqual(r['dependency']['to'],'Other');self.assertEqual(r['duplicate']['samples'][0]['a'],'App/logo.svg');self.assertEqual(r['background']['samples'][0]['sha256'],'ab'*32)
 def test_identical_packages_do_not_invent_dependencies(self):
  d=self.manifest();d['projectReferences']=[];index=build_relations(d);self.assertFalse(any(r['kind']=='dependency' for p in index['pairs'] for r in p['relations']))
 def test_direction_archive_and_no_intraunit_noise(self):
  d=self.manifest();d['duplicates'].append(['App/logo.svg','App/src/main.ts']);index=build_relations(d);self.assertFalse(any(p['a']==p['b'] for p in index['pairs']));r=next(r for p in index['pairs'] for r in p['relations'] if r['kind']=='archive');self.assertEqual((r['from'],r['to']),('Archive.zip','App'))
 def test_empty_and_metadata_files_ignored(self):
  d=self.manifest();d['duplicates']=[['App/logo.svg','Other/logo.svg']];d['records'][1]['size']=0;d['records'][3]['size']=0;index=build_relations(d);self.assertFalse(any(r['kind']=='duplicate' for p in index['pairs'] for r in p['relations']))
if __name__=='__main__':unittest.main()
