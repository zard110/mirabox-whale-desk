import colorsys,json,math,random,re,subprocess,time
from pathlib import Path
from gifts import SCENES, draw_gift
from PIL import Image,ImageDraw,ImageFont

ROOT=Path(__file__).resolve().parents[2]
BANK=ROOT/'maid-voice'
TIMING=json.loads((BANK/'caption-timing.json').read_text())
EVENT=Path.home()/'.local/state/whale-presence/speech-event.json'
TITLES={'return':'欢迎归来','looking':'四目相遇','working':'陪您工作','away':'一路顺风','visitor_here':'来客通报','visitor_away':'女仆接待','visitor_unsure':'女仆接待'}
FONT='/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'

def angle_sequence():
    previous=None
    while True:
        bag=[sign*random.uniform(low,high) for sign in (-1,1)
             for low,high in ((2.8,3.6),(3.8,4.6),(4.9,5.9))]
        while bag:
            choices=[i for i,value in enumerate(bag) if previous is None or abs(previous-value)>=1.2]
            if not choices:break
            previous=bag.pop(random.choice(choices))
            yield previous

ANGLES=angle_sequence()

def card(text,scene,*,angle=None):
    if angle is None:angle=next(ANGLES)
    font=ImageFont.truetype(FONT,239,index=2)
    chars=[c for c in text if not c.isspace()]
    positions=[];y=5
    punctuation=str.maketrans({'，':'︐','。':'︒','、':'︑','！':'︕','？':'︖','：':'︓','…':'︙'})
    for char in chars:
        short=char in '，。、！？，：…'
        glyph=char.translate(punctuation)
        box=font.getbbox(glyph,stroke_width=3)
        step=max(103 if short else 246,box[3]-box[1]+8)
        positions.append((glyph,y+step//2));y+=step
    tile=Image.new('RGBA',(231,y+6))
    for i,(char,cy) in enumerate(positions):
        color=tuple(round(v*255) for v in colorsys.hsv_to_rgb((.48+i*.069)%1,.42,1))
        box=font.getbbox(char,stroke_width=3)
        glyph=Image.new('RGBA',(box[2]-box[0],box[3]-box[1]))
        ImageDraw.Draw(glyph).text((-box[0],-box[1]),char,font=font,fill=color,stroke_width=3,stroke_fill=(16,13,49,226))
        if glyph.width>231:glyph.thumbnail((231,glyph.height),Image.Resampling.LANCZOS)
        tile.alpha_composite(glyph,((231-glyph.width)//2,cy-glyph.height//2))
    tile=tile.rotate(angle,Image.Resampling.BICUBIC,expand=True)
    tile.info['slope']=math.tan(math.radians(angle))
    return tile

def paint(frame,tile,elapsed,duration,offset_y=608):
    progress=elapsed*TIMING['scroll_speed']/(duration+TIMING['tail_seconds'])
    if not 0<=progress<1:return
    top=round(1920-progress*(1920+tile.height))-offset_y
    if top>=frame.height or top+tile.height<=0:return
    center_y=top+offset_y+tile.height/2
    x=round((frame.width-tile.width)/2+(center_y-960)*tile.info['slope'])
    frame.paste(tile,(x,top),tile)

class Captions:
    def __init__(self):
        self.next_poll=0;self.seen=None;self.tile=None;self.started=0;self.duration=0;self.player=None
        self.gift=None;self.gift_seed=0
    def draw(self,frame):
        now=time.monotonic()
        if now>=self.next_poll:
            self.next_poll=now+.12
            try:
                e=json.loads(EVENT.read_text())
                if e['id']!=self.seen and 0<=time.time()-e['at']<1.5 and e['scene'] in TITLES and re.fullmatch(r'[a-z_]+-\d+',e['key']):
                    self.seen=e['id'];self.tile=card(e['text'],e['scene']);self.duration=float(e['duration']);self.started=time.monotonic()
                    self.gift=SCENES.get(e['scene']) if e.get('audio',True) else None
                    self.gift_seed=e['id']
                    if self.player and self.player.poll() is None:self.player.terminate()
                    if e.get('audio',True):self.player=subprocess.Popen(['pw-play',str(BANK/'clips'/(e['key']+'.wav'))],stdout=subprocess.DEVNULL)
                    print('字幕开始:',e['key'],flush=True)
            except (OSError,ValueError,KeyError,TypeError):pass
        self.frame_elapsed=time.monotonic()-self.started
        draw_gift(frame,self.gift,self.frame_elapsed,self.gift_seed)
        if self.tile is not None:paint(frame,self.tile,self.frame_elapsed,self.duration)

    def active(self):
        return self.tile is not None and self.frame_elapsed*TIMING['scroll_speed']<self.duration+TIMING['tail_seconds']

    def upper(self,frame):
        if self.tile is not None:paint(frame,self.tile,self.frame_elapsed,self.duration,0)
