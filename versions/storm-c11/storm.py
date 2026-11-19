from datetime import datetime
from functools import lru_cache
from pathlib import Path
import math
import owner_strip
from subtitles import Captions
from crt import CameraTV
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT=Path(__file__).resolve().parent
ASSETS=ROOT/'assets'
SIZE=(462,1920)
TOP=608
HERO=(0,TOP,462,1920)
HEADER=(0,0,462,80)
UPPER=(0,0,462,TOP)
ACCENT={'typing':'#ffc06d','dancing':'#c8a4ff','slacking':'#68e6fa'}
WHITE='#f3f9ff'; SOFT='#adcbeb'; AQUA='#73f4ef'; BLUE='#85baff'

@lru_cache(maxsize=100)
def font(size,face):
    path={'number':'/usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf','display':'/usr/share/fonts/opentype/urw-base35/NimbusSansNarrow-Regular.otf','label':'/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc','caption':'/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc','italic':'/usr/share/fonts/opentype/urw-base35/NimbusSans-Italic.otf'}[face]
    return ImageFont.truetype(path,size,index=2 if face in ('label','caption') else 0)

def text(draw,xy,value,size,color=WHITE,face='number',anchor='lm'):
    draw.text(xy,str(value),font=font(size,face),anchor=anchor,fill=color,stroke_width=1,stroke_fill='#10223c')

def amount(value,byte=False):
    if value is None:return '—'
    if byte:
        for unit in ('B','KB','MB','GB','TB'):
            if value<1024 or unit=='TB':return f'{value:.1f}',unit
            value/=1024
    for base,unit in [(1e9,'B'),(1e6,'M'),(1e3,'K')]:
        if value>=base:return f'{value/base:.2f}'.rstrip('0').rstrip('.')+unit
    return f'{value:.0f}'

def reset_countdown(reset_at,now):
    if not isinstance(reset_at,(float,int)) or not math.isfinite(reset_at) or reset_at<=now:
        return '—'
    seconds=reset_at-now
    if seconds>=86400:
        days,hours=divmod(int(seconds//3600),24)
        return f'{days}天{hours:02}小时'
    hours,minutes=divmod(max(1,int(seconds//60)),60)
    return f'{hours}小时{minutes:02}分'

def glass(im,box):
    x,y,w,h=box; plate=Image.open(ASSETS/'glass.png').convert('RGBA');cut=13
    srcx=[0,cut,plate.width-cut,plate.width];srcy=[0,cut,plate.height-cut,plate.height]
    destx=[0,cut,w-cut,w];desty=[0,cut,h-cut,h]
    for row in range(3):
        for col in range(3):
            if row==1 and col==1:continue
            rect=(srcx[col],srcy[row],srcx[col+1],srcy[row+1]); piece=plate.crop(rect).resize((destx[col+1]-destx[col],desty[row+1]-desty[row]),Image.Resampling.BILINEAR)
            im.paste(piece,(x+destx[col],y+desty[row]),piece)

def panel(im,box):
    x,y,w,h=box
    sub=Image.new('RGBA',(w,h));draw=ImageDraw.Draw(sub)
    for sy in range(1,h-1):
        taper=max(1,11-min(sy,h-sy));phase=sy/h
        shade=math.exp(-phase*5);draw.line((taper,sy,w-1-taper,sy),fill=(int(5+19*shade),int(18+23*shade),int(43+31*shade),228))
    im.paste(sub,(x,y),sub);glass(im,box)

def bar(draw,box,fraction,color):
    left,top,right,bottom=box;r=max(1,(bottom-top)//2);draw.rounded_rectangle(box,r,fill='#223e69')
    if fraction is not None and fraction>0:
        end=left+max(2,round((right-left)*min(1,fraction)));draw.rounded_rectangle((left,top,end,bottom),r,fill=color)

class Renderer:
    def __init__(self):
        self.captions=Captions()
        self.tv=CameraTV()
        self.top=Image.open(ASSETS/'upper.jpg').convert('RGB');self.chrome=self.top.copy()
        for box in [(14,296,213,98),(234,296,214,98),(14,407,434,178)]:panel(self.chrome,box)
        self.tank=Image.open(ASSETS/'tank.png').convert('RGBA');bbox=self.tank.getchannel('A').point(lambda v:255 if v>16 else 0).getbbox();self.tank=self.tank.crop(bbox).resize((432,48),Image.Resampling.LANCZOS)
        logo=Image.open(ASSETS/'deepseek-logo.png').convert('RGBA').resize((42,32),Image.Resampling.LANCZOS);self.logo=Image.new('RGBA',logo.size,'#a8faff');self.logo.putalpha(logo.getchannel('A'))
        self.header_base=self.top.crop(HEADER);self.header_base.paste(self.tank,(15,17),self.tank)
        self.paths={mode:sorted((ASSETS/mode).glob('*.jpg')) for mode in ACCENT}
        if not all(self.paths.values()):raise RuntimeError('Missing native scene frames')
        mask=Image.new('L',self.chrome.size);lines=ImageDraw.Draw(mask)
        for x,y,w,h in [(14,296,213,98),(234,296,214,98),(14,407,434,178)]:
            lines.line([(x+2,y+h-11),(x+11,y+h-2),(x+w-12,y+h-2),(x+w-2,y+h-11)],fill=205,width=3);lines.line([(x+w-48,y+2),(x+w-11,y+2),(x+w-2,y+12)],fill=112,width=2)
        mask=ImageChops.screen(mask.filter(ImageFilter.GaussianBlur(4.2)),mask);self.rims={mode:ImageOps.colorize(mask,'black',color) for mode,color in ACCENT.items()}

    def header(self,now):
        im=self.header_base.copy();phase=(now.second+now.microsecond/1e6)/60;im.paste(self.logo,(round(24+phase*370),25),self.logo);return im

    @property
    def owner_pose(self):
        return self.tv.posture or self.reported_pose

    def update(self,values,energy,mode,busy,now=None):
        self.reported_pose=owner_strip.status()
        now=now or datetime.now(); self.mode=mode;im=self.chrome.copy();draw=ImageDraw.Draw(im)
        text(draw,(111,169),now.strftime('%H:%M'),84,WHITE,'display','mm')
        draw.line((43,218,174,218),fill='#5b889b');draw.ellipse((105,216,109,220),fill='#dfbc88')
        text(draw,(111,243),now.strftime('%Y.%m.%d')+'  周'+'一二三四五六日'[now.weekday()],18,'#d8eaff','caption','mm')
        for offset,title,key in [(14,'CPU','cpu'),(234,'MEMORY','memory')]:
            val=values[key];text(draw,(offset+17,323),title,16,SOFT,'display');text(draw,(offset+17,355),f'{val:.0f}%',37,WHITE,'number')
            extra=(('—' if values['temperature'] is None else f"{values['temperature']:.0f}°C") if key=='cpu' else f"{values['memory_gb']:.1f} GB")
            text(draw,(offset+194,353),extra,20,AQUA if key=='cpu' else BLUE,'display','rm');bar(draw,(offset+18,378,offset+194,384),val/100,AQUA if key=='cpu' else BLUE)
        draw.line((230,424,230,568),fill='#315078')
        for xpos,label,total,history,color in [(33,'↓ 下载','total_download','down_history',AQUA),(248,'↑ 上传','total_upload','up_history',BLUE)]:
            key='down' if total=='total_download' else 'up';value,unit=amount(values[key],True)
            text(draw,(xpos,433),label+'速度',16,color,'label');text(draw,(xpos,465),value,34,WHITE);width=draw.textlength(value,font=font(34,'number'));text(draw,(xpos+width+6,469),unit+'/s',17,color,'display')
            hist=values[history];peak=max(1024,*values['down_history'],*values['up_history']);end=xpos+176
            for yy in [494,524]:draw.line((xpos,yy,end,yy),fill='#25436a')
            points=[(xpos+index*176/max(1,len(hist)-1),523-v/peak*28) for index,v in enumerate(hist)];
            if len(points)>1:draw.line(points,fill=color,width=2,joint='curve')
            text(draw,(xpos,548),'累计'+label[2:],14,SOFT,'caption');v,u=amount(values[total],True);text(draw,(end,550),v+' '+u,21,color,'display','rm')
        self.upper=im;self.lit=ImageChops.screen(im,self.rims[mode]); self.overlay=Image.new('RGBA',(287,425));d=ImageDraw.Draw(self.overlay);accent=ACCENT[mode]
        usage=values.get('usage') or {};left=18
        text(d,(left+5,52),'AI 用量',26,WHITE,'label');badge=(119,33,198,67);bx,by,ex,ey=badge;d.polygon([(bx+9,by),(ex,by+3),(ex-8,ey),(bx,ey-3)],fill='#203468',outline=accent,width=2);text(d,(159,49),'运算中' if any(busy.values()) else '空闲',17,WHITE,'label','mm')
        text(d,(left+7,99),usage.get('quota_label','周额度')+'剩余',16,SOFT,'caption');frac=usage.get('quota_remaining');text(d,(left+5,148),'—' if frac is None else f'{frac:.0f}%',65,'#ffbb53','italic');bar(d,(left+5,183,162,190),None if frac is None else frac/100,'#ffbd59')
        clock=reset_countdown(usage.get('quota_reset_at'),now.timestamp())
        text(d,(left+6,212),'重置',14,SOFT,'caption');text(d,(169,212),clock,20,accent,'label','rm')
        v='∞' if usage.get('credits_unlimited') else amount(usage.get('credits'));text(d,(left+5,251),v,33,WHITE,'display');ww=d.textlength(v,font=font(33,'display'));text(d,(left+10+ww,254),'Credits',16,SOFT,'display');d.line((left+5,273,169,273),fill='#3f6995')
        for row,(label,key) in enumerate([('Codex','codex_tokens'),('DeepSeek','deepseek_tokens')]):
            yy=299+row*36;text(d,(left+6,yy),label,17,SOFT);text(d,(177,yy),amount(usage.get(key)),22,WHITE,'display','rm')
        text(d,(left+6,379),'Token · 含缓存',14,SOFT,'caption')
        self.gauge=Image.new('RGBA',(364,29));g=ImageDraw.Draw(self.gauge);g.rounded_rectangle((0,0,363,28),14,fill='#071c3c',outline='#75bde4',width=2);bar(g,(7,7,356,21),energy/100,'#8adeff')

    @lru_cache(maxsize=5)
    def read(self,mode,index):
        with Image.open(self.paths[mode][index]) as im:return im.convert('RGB')

    def scene(self,mode,elapsed):
        files=self.paths[mode];return self.read(mode,int(max(0,elapsed)*24)%len(files))

    def hero(self,mode,elapsed,previous=None):
        current=self.scene(mode,elapsed)
        if previous is not None and elapsed<.42:
            phase=min(1,elapsed/.42);current=Image.blend(previous,current,phase*phase*(3-2*phase))
        else:current=current.copy()
        current.paste(self.overlay,(0,88),self.overlay)
        badge=owner_strip.tile(self.owner_pose,int(elapsed*14)%32)
        current.paste(badge,(67,1156),badge)
        current.paste(self.gauge,(49,1268),self.gauge);self.captions.draw(current);return current

    def top_at(self,now,elapsed):
        phase=(int(max(0,elapsed)*24)%len(self.paths[self.mode]))/len(self.paths[self.mode]);beat=phase*({'typing':12,'dancing':10,'slacking':2}[self.mode])%1
        level=.15+.20*(1+math.cos(beat*math.tau)) if self.mode=='slacking' else .12+.83*math.exp(-beat*5.8)*min(1,beat/.075)
        im=Image.blend(self.upper,self.lit,level);im.paste(self.header(now),(0,0));self.tv.draw(im);self.captions.upper(im);return im

    def full(self,hero,now=None,elapsed=0):
        im=Image.new('RGB',SIZE);im.paste(self.top_at(now or datetime.now(),elapsed));im.paste(hero,(0,TOP));return im
