"""Render captured actual terminal-cell frames for visual inspection (Pillow only for QA)."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from PIL import Image, ImageDraw, ImageFont
from peekcli.colors import RGB
from peekcli.text import cell_width
source=Path(sys.argv[1]);output=Path(sys.argv[2]);output.mkdir(parents=True,exist_ok=True)
frames=json.loads(source.read_text())
font=ImageFont.truetype('/System/Library/Fonts/Menlo.ttc',15)
cell_w,cell_h=10,22
for key in ['apps','brew','files','security','services','dev','help','diagnostics','intro','detail']:
 if key not in frames:continue
 frame=frames[key];image=Image.new('RGB',(frame['width']*cell_w+24,frame['height']*cell_h+24),RGB['background']);draw=ImageDraw.Draw(image)
 for span in frame['spans']:
  x=12+span['x']*cell_w;y=12+span['y']*cell_h
  color=RGB.get(span['role'],RGB['text'])
  if span['selected']:
   draw.rectangle((x,y,x+cell_width(span['text'])*cell_w,y+cell_h),fill=RGB['logo']);color=RGB['background']
  offset=0
  for ch in span['text']:
   draw.text((x+offset*cell_w,y),ch,font=font,fill=color)
   offset+=cell_width(ch)
 image.save(output/(key+'.png'))
 print(output/(key+'.png'))
