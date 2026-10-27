"""QA previews from actual ncurses text/attribute readback; the canvas is supplied by QA."""
import json,sys
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from peekcli.text import cell_width
frames=json.loads(Path(sys.argv[1]).read_text());out=Path(sys.argv[2]);out.mkdir(parents=True,exist_ok=True)
light=len(sys.argv)>3 and sys.argv[3]=='light'
background='#fafafa' if light else '#1e1e1e';foreground='#202020' if light else '#e9e9e9'
font=ImageFont.truetype('/System/Library/Fonts/Menlo.ttc',15)
wide_font=ImageFont.truetype('/System/Library/Fonts/Hiragino Sans GB.ttc',15)
bold=ImageFont.truetype('/System/Library/Fonts/Menlo.ttc',15,index=1)
def color(index):
 if index<0:return foreground
 ansi=['#000000','#cd0000','#00cd00','#cdcd00','#0000ee','#cd00cd','#00cdcd','#e5e5e5','#7f7f7f','#ff0000','#00ff00','#ffff00','#5c5cff','#ff00ff','#00ffff','#ffffff']
 if index<16:return ansi[index]
 if index>=232:
  gray=8+(index-232)*10;return '#'+f'{gray:02x}'*3
 index-=16;levels=[0,95,135,175,215,255];return '#'+''.join(f'{levels[x]:02x}' for x in [index//36,index//6%6,index%6])
for name,frame in frames.items():
 if name.removesuffix('-pt_BR') not in {'intro','apps','detail-apps','brew','detail-brew','settings','help-0','help-2','dev','resized-apps'}:continue
 image=Image.new('RGB',(frame['width']*10+24,frame['height']*22+24),background);draw=ImageDraw.Draw(image)
 for y,line in enumerate(frame['native_rows']):
  x=0
  for char in line:
   width=cell_width(char)
   if x>=frame['width']:break
   if not width:continue
   style=frame['native_styles'][y][x]
   fg,is_bold,reverse,underline,dim=style[:5]
   text_color=color(fg);cell_background=color(style[5]) if len(style)>5 and style[5]>=0 else background
   if dim:
    rgb=tuple(int(text_color[i:i+2],16) for i in [1,3,5]);bg=tuple(int(background[i:i+2],16) for i in [1,3,5]);text_color='#'+''.join(f'{round(a*.65+b*.35):02x}' for a,b in zip(rgb,bg))
   if reverse:text_color,cell_background=background,text_color
   px,py=12+x*10,12+y*22
   if cell_background!=background:draw.rectangle((px,py,px+width*10-1,py+21),fill=cell_background)
   draw.text((px,py),char,font=wide_font if width==2 else bold if is_bold else font,fill=text_color)
   if underline:draw.line((px,py+20,px+width*10-1,py+20),fill=text_color)
   x+=width
 image.save(out/(name+'.png'));print(out/(name+'.png'))
