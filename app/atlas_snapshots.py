"""Atomic scan selection; previous scans and execution journals remain intact."""
import json,os,re
from pathlib import Path
from apply_plan import no_links

def snapshot_folder(storage):
 storage=Path(storage);pointer=storage/'current-snapshot.json';no_links(pointer)
 if not pointer.exists():return storage
 ident=json.loads(pointer.read_text()).get('snapshot')
 if not isinstance(ident,str) or not re.fullmatch('[0-9a-f]{32}',ident):raise ValueError('Invalid saved scan reference')
 folder=no_links(storage/'snapshots'/ident)
 for name in ('scan.json','Downloads Organizer.html','connections.json'):
  file=no_links(folder/name)
  if not file.is_file():raise ValueError('The refreshed scan is incomplete; previous snapshots are retained')
 return folder

def publish_snapshot(storage,ident):
 if not re.fullmatch('[0-9a-f]{32}',ident):raise ValueError('Invalid scan identity')
 storage=Path(storage);temp=no_links(storage/('current-snapshot-'+ident+'.tmp'));pointer=no_links(storage/'current-snapshot.json')
 with temp.open('w') as out:json.dump({'snapshot':ident},out);out.flush();os.fsync(out.fileno())
 os.replace(temp,pointer)
