import io
import json
import os
import socket
import time
from pathlib import Path

from owner_strip import LABEL as OWNER_STATES

import gi
gi.require_version('Rsvg','2.0')
from gi.repository import Rsvg
from PIL import Image,ImageDraw,ImageFont

ORIGIN=(216,83)
SCREEN=(176,132)
LABELS={'owner':('主人','#82ffe9'),'guest':('陌生人','#ffce83'),'pending':('未识别','#d2c8ff')}

def cabinet():
    svg="""<svg xmlns="http://www.w3.org/2000/svg" width="476" height="400" viewBox="0 0 238 200">
    <defs>
      <linearGradient id="shell" x2=".24" y2="1" gradientUnits="objectBoundingBox"><stop stop-color="#b9eae4"/><stop offset=".10" stop-color="#64aeb5"/><stop offset=".46" stop-color="#3c808f"/><stop offset=".94" stop-color="#285366"/><stop offset="1" stop-color="#163044"/></linearGradient>
      <linearGradient id="brass" x2=".8" y2="1"><stop stop-color="#ffdfad"/><stop offset=".34" stop-color="#deac76"/><stop offset=".76" stop-color="#916644"/><stop offset="1" stop-color="#e4c69a"/></linearGradient>
      <radialGradient id="dial"><stop stop-color="#457585"/><stop offset=".75" stop-color="#264b5f"/><stop offset="1" stop-color="#102735"/></radialGradient>
      <pattern id="grille" width="4" height="4" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.05" fill="#0d2c3c"/></pattern>
    </defs>
    <ellipse cx="120" cy="196" rx="111" ry="4" fill="#061328" opacity=".65"/>
    <path d="M22 181l-3 14q5 4 12 0l8-14m148 0 6 14q7 3 13-1l-3-14" fill="#203948" stroke="#bd9f76" stroke-width="1.3"/>
    <g fill="none" stroke-linecap="round"><path d="M108 30L72 5m38 26 42-28" stroke="#173444" stroke-width="3.7"/><path d="M108 29L72 4m38 26 42-28" stroke="#c7ded8" stroke-width="1.6"/></g>
    <g fill="#ffd89e"><circle cx="72" cy="4" r="2.2"/><circle cx="152" cy="2" r="1.8"/></g>
    <path d="M99 29q8-13 21 0" fill="url(#brass)" stroke="#4d504b"/>
    <rect x="3" y="26" width="231" height="164" rx="20" fill="#132739" stroke="#132537" stroke-width="3"/>
    <rect x="2" y="24" width="231" height="162" rx="19" fill="url(#shell)" stroke="#b3dcd7" stroke-width="1.2"/>
    <rect x="7" y="31" width="187" height="146" rx="18" fill="#214954" stroke="#a4d3cc" stroke-width="1.2"/>
    <rect x="9" y="34" width="182" height="141" rx="16" fill="#0c1e2d" stroke="#223442" stroke-width="2"/>
    <rect x="197" y="36" width="29" height="136" rx="10" fill="#3c7180" stroke="#80abb0"/>
    <path d="M200 56a12 12 0 0 1 23 0" fill="none" stroke="#f7d6a6" stroke-dasharray="1.1 3"/>
    <circle cx="212" cy="58" r="10.4" fill="url(#brass)"/><circle cx="212" cy="58" r="7.7" fill="url(#dial)"/>
    <path d="M210 59l5-6" stroke="#ffd598" stroke-width="2" stroke-linecap="round"/>
    <circle cx="212" cy="85" r="8.2" fill="url(#brass)"/><circle cx="212" cy="85" r="5.5" fill="url(#dial)"/>
    <path d="M212 85l-3-3" stroke="#ffe0b8" stroke-width="1.5"/>
    <rect x="201" y="102" width="21" height="56" rx="8" fill="url(#grille)"/>
    <path d="M15 179h42m85 0h44" stroke="#93bfc0" opacity=".7"/>
    <text x="100" y="183" fill="#f3e5c5" text-anchor="middle" font-family="sans-serif" font-weight="bold" font-size="6.9" letter-spacing="2.2">PELAGIC TV</text>
    </svg>"""
    pix=Rsvg.Handle.new_from_data(svg.encode()).get_pixbuf()
    _,png=pix.save_to_bufferv('png',[],[]);return Image.open(io.BytesIO(png)).convert('RGBA').resize((238,200),Image.Resampling.LANCZOS)

class CameraTV:
    def __init__(self):
        self.case=cabinet();self.sock=None;self.seen=-100.;self.frames=0;self.box_count=0
        self.label=ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc',11,index=2)
        self.mask=Image.new('L',(352,264));ImageDraw.Draw(self.mask).rounded_rectangle((0,0,351,263),24,fill=255)
        self.mask=self.mask.resize(SCREEN,Image.Resampling.LANCZOS)
        self.off=Image.new('RGB',SCREEN,'#112735');p=ImageDraw.Draw(self.off)
        for y in range(0,132,4):p.line((0,y,176,y),fill='#162f3d')
        p.text((88,66),'等待摄像信号',font=self.label,fill='#99bdc9',anchor='mm')
        self.image=None
        self.posture=None

    def listen(self):
        path=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))/'whale-d92-tv.sock'
        path.unlink(missing_ok=True)
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
        self.sock.bind(str(path));os.chmod(path,0o600);self.sock.setblocking(False)

    def picture(self,image,boxes):
        image=image.convert('RGB').resize(SCREEN,Image.Resampling.LANCZOS)
        pen=ImageDraw.Draw(image)
        for x,y,w,h,tag in boxes:
            if tag not in LABELS:continue
            left=max(2,min(171,round(x*.55)));right=max(left+2,min(173,round((x+w)*.55)))
            top=max(2,min(127,round(y*.55)));bottom=max(top+2,min(129,round((y+h)*.55)))
            label,color=LABELS[tag];arm=min(6,(right-left)//2,(bottom-top)//2)
            for xx,dx in ((left,1),(right,-1)):
                for yy,dy in ((top,1),(bottom,-1)):
                    pen.line([(xx+dx*arm,yy),(xx,yy),(xx,yy+dy*arm)],fill='#172a36',width=3)
                    pen.line([(xx+dx*arm,yy),(xx,yy),(xx,yy+dy*arm)],fill=color,width=1)
            width=round(self.label.getlength(label))+6;tx=min(left,172-width);ty=top-15 if top>=18 else bottom+2 if bottom<113 else top
            pen.rounded_rectangle((tx,ty,tx+width,ty+13),3,fill='#102837');pen.text((tx+3,ty+6),label,font=self.label,anchor='lm',fill=color)
        return image

    def update(self):
        now=time.monotonic();packet=None
        if self.sock:
            for _ in range(32):
                try:packet=self.sock.recv(65536)
                except BlockingIOError:break
        if packet:
            try:
                header,jpeg=packet.split(b'\n',1)
                stamp,boxes,*state=json.loads(header)
                if 0<=now-stamp<1.5:
                    with Image.open(io.BytesIO(jpeg)) as image:self.image=self.picture(image,boxes)
                    self.posture=state[0] if state and state[0] in OWNER_STATES else None
                    self.seen=stamp;self.frames+=1;self.box_count=len(boxes)
            except (ValueError,TypeError,OSError):pass
        live=self.image is not None and now-self.seen<1.5
        if not live:self.image=None;self.box_count=0;self.posture=None

    def draw(self,frame):
        live=self.image is not None
        x,y=ORIGIN;frame.paste(self.case,ORIGIN,self.case);frame.paste(self.image if live else self.off,(x+12,y+38),self.mask)
        ImageDraw.Draw(frame).ellipse((x+209,y+162,x+214,y+167),fill='#9affd5' if live else '#bc9169')
