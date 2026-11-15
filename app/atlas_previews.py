import shutil,json,io,base64,concurrent.futures,subprocess,collections,time,warnings
from pathlib import Path
from PIL import Image,ImageOps,ImageFont,ImageDraw
warnings.simplefilter('ignore');Image.MAX_IMAGE_PIXELS=100_000_000
def previews(manifest,progress=lambda **kwargs:None,cancelled=lambda:False):
 D=manifest;root=Path(D['root']);members=collections.defaultdict(list)
 for r in D['records']:
  if r['kind']=='file':members[r['unit']].append(r)
 result={}
 RASTER={'.png','.jpg','.jpeg','.webp','.gif','.bmp','.psd'};VIDEO={'.mp4','.mov','.webm','.m4v'}
 def make(u):
  name=u['path']
  if name in result:return name,result[name]
  entries=members[name];fonts=[r for r in entries if r.get('family') and r['ext'] in {'.ttf','.otf'}]
  ims=sorted([r for r in entries if r['ext'] in RASTER],key=lambda r:(r['ext']=='.psd',bool(r['name'].startswith('.')),r['size']<10000,'preview' not in r['name'].lower(),r['size']))
  vids=[r for r in entries if r['ext'] in VIDEO];choices=(fonts[:1] if u['families'] and not u['locked'] else [])+ims[:8]+vids[:1]
  for r in choices:
   p=root/r['path']
   try:
    if p.is_symlink():continue
    if r in fonts:
     im=Image.new('RGB',(340,240),'#eeede6');draw=ImageDraw.Draw(im);font=ImageFont.truetype(str(p),64);draw.text((22,12),'Aa',font=font,fill='#333630');draw.text((22,103),'012345',font=ImageFont.truetype(str(p),34),fill='#55574f');draw.text((22,160),'Type & texture',font=ImageFont.truetype(str(p),23),fill='#55574f')
    elif r['ext'] in VIDEO:
     b=subprocess.run([shutil.which('ffmpeg') or 'ffmpeg','-v','error','-ss','0.4','-i',str(p),'-frames:v','1','-vf','scale=340:240:force_original_aspect_ratio=decrease','-f','image2pipe','-vcodec','mjpeg','-threads','1','-'],capture_output=True,timeout=15).stdout
     im=Image.open(io.BytesIO(b));im.load()
    else:
     with Image.open(p) as src:
      src=ImageOps.exif_transpose(src);src.thumbnail((340,240));im=Image.new('RGB',src.size,'#f1f0eb')
      if src.mode in ('RGBA','LA') or 'transparency' in src.info:im.paste(src.convert('RGBA'),mask=src.convert('RGBA').getchannel('A'))
      else:im.paste(src.convert('RGB'))
    im.thumbnail((340,240));buf=io.BytesIO();im.convert('RGB').save(buf,format='JPEG',quality=72,optimize=True)
    return name,{'src':'data:image/jpeg;base64,'+base64.b64encode(buf.getvalue()).decode(),'file':r['path'],'type':'font' if r in fonts else 'video' if r['ext'] in VIDEO else 'image'}
   except Exception:continue
  return name,{'file':next((r['path'] for r in entries if r['ext']=='.svg'),None),'type':'vector'}
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
  for i,(name,res) in enumerate(pool.map(make,D['units'])):
   if cancelled():raise ValueError('Scan cancelled. No files were changed.')
   result[name]=res
   progress(phase='previews',message='Making visual previews…',completed=i+1,total=len(D['units']))
 return result
