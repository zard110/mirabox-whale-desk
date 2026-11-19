from functools import lru_cache
import json
from pathlib import Path
import time
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parent
STATUS=Path.home()/'.local/state/whale-presence/status.json'
LABEL={'present':('主人在场','OWNER PRESENT','#82ffe9'),'looking':('主人在看我','EYE CONTACT','#97eeff'),'working':('主人在工作','AT THE DESK','#cebaff'),'away':('主人离开了','OWNER AWAY','#a8bad7'),'unknown':('摄像信号不足','LOW SIGNAL','#9cafc7'),
       'no_face':('未见人脸','NO FACE IN VIEW','#a8bad7'),
       'unrecognized':('未认出主人','OWNER UNIDENTIFIED','#baaed2'),
       'guests_only':('仅见访客','GUEST IN VIEW','#ffce83')}

def status():
    try:
        sample=json.loads(STATUS.read_text());value=sample['posture']
        return value if value in LABEL and 0<=time.time()-sample['time']<8 else 'unknown'
    except (OSError,ValueError,KeyError,TypeError):return 'unknown'

@lru_cache(maxsize=4)
def sheet(mode):
    with Image.open(ROOT/'assets'/('owner-'+mode+'.png')) as im:return im.convert('RGBA')

@lru_cache(maxsize=128)
def tile(mode,index):
    label,subtitle,accent=LABEL[mode];im=Image.new('RGBA',(328,103));draw=ImageDraw.Draw(im)
    for x in range(328):
        fade=min(1,x/26,(327-x)/47)
        draw.line((x,10,x,96),fill=(3,12,30,int(160*fade)))
    draw.line((119,27,119,78),fill=accent,width=2)
    zh=ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc',23,index=2)
    en=ImageFont.truetype('/usr/share/fonts/opentype/urw-base35/NimbusSansNarrow-Bold.otf',13)
    draw.text((132,44),label,font=zh,fill='#eef8ff',anchor='lm')
    draw.text((133,73),subtitle,font=en,fill=accent,anchor='lm')
    sprite={'present':'looking','no_face':'away','unrecognized':'unknown','guests_only':'unknown'}.get(mode,mode)
    im.alpha_composite(sheet(sprite).crop((index*116,0,(index+1)*116,103)));return im
