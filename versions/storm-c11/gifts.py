"""Live gift effects drawn in the hero area, underneath the scrolling captions."""
from functools import lru_cache
import math
from PIL import Image, ImageDraw, ImageFilter, ImageChops

DURATION = 4.4
SCENES = {'return': 'pearl', 'looking': 'heart', 'visitor_here': 'parcel',
          'visitor_away': 'parcel', 'visitor_unsure': 'parcel'}


@lru_cache(maxsize=8)
def jewel(kind):
    art = Image.new('RGBA', (128, 128))
    pen = ImageDraw.Draw(art)
    if kind == 'heart':
        outline = []
        for i in range(101):
            t = math.tau * i / 100
            x = 64 + 3.05 * 16 * math.sin(t)**3
            y = 58 - 3.05 * (13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t))
            outline.append((x,y))
        pen.polygon(outline, fill='#ff568e', outline='#ffe6f3', width=3)
        pen.polygon([(18,48),(40,27),(53,54),(64,103)],fill='#ff9fc5')
        pen.polygon([(53,54),(92,31),(107,47),(64,103)], fill='#ff73ae')
        pen.polygon([(53,54),(64,103),(33,71)],fill='#df407e')
        pen.line([(26,46),(34,35),(42,32)],fill='#fff5fa',width=4)
    elif kind == 'pearl':
        pen.ellipse((23,23,105,105),fill='#7cb8ce',outline='#e5ffff',width=3)
        for r in range(38,0,-1):
            v=1-r/38
            x,y=64-12*v,64-13*v
            pen.ellipse((x-r,y-r,x+r,y+r),fill=(int(158+97*v),int(211+42*v),int(238+17*v)))
        pen.arc((28,28,100,100),18,125,fill='#e4bfff',width=4)
        pen.ellipse((42,38,54,48), fill='white')
    elif kind == 'shell':
        edge=[(9,59),(12,45),(21,41),(25,30),(37,29),(44,20),(56,22),
              (64,15),(73,21),(86,20),(93,29),(105,30),(110,40),(117,44),(120,57)]
        foot=(64,108)
        pen.polygon(edge+[foot],fill='#9b73cf',outline='#ffe5ee',width=3)
        for i in range(0,len(edge)-1,2):
            pen.polygon([foot,edge[i],edge[i+1]], fill='#e3b8ec')
            pen.line([foot,edge[i]], fill='#ffe5ee',width=2)
        pen.ellipse((47,103,81,112),fill='#fad3c0',outline='#fff0d8',width=2)
    elif kind == 'box':
        pen.polygon([(17,43),(63,54),(110,42),(107,91),(63,109),(21,93)],fill='#6b52c9',outline='#fae6ff',width=3)
        pen.polygon([(18,44),(63,55),(63,106),(22,91)],fill='#ad86f1')
        pen.polygon([(34,49),(47,52),(49,101),(36,96)],fill='#ffdb94')
        pen.polygon([(82,51),(95,47),(93,96),(81,101)],fill='#efac75')
        pen.line([(20,88),(63,103),(106,87)],fill='#dec2fb',width=2)
    elif kind == 'lid':
        pen.polygon([(12,54),(63,40),(115,52),(114,63),(63,77),(13,66)],fill='#bb98ef',outline='#fff0d4',width=3)
        pen.polygon([(12,54),(63,40),(115,52),(63,66)],fill='#ead4ff',outline='#fff0e1')
        for side in (-1,1):
            pen.polygon([(64,51),(64+side*20,27),(64+side*34,29),(64+side*31,43)],fill='#ecaa77',outline='#fff1ba',width=3)
            pen.line([(63,53),(64+side*21,35),(64+side*25,36)], fill='#ffdd9b',width=2)
        pen.ellipse((57,44,70,57),fill='#ffe5a1',outline='#fff6dc')
    else:
        pen.polygon([(64,11),(73,50),(103,63),(74,72),(64,116),(54,74),(20,64),(54,53)],
                    fill='#ffe7ac',outline='#fffcea',width=3)
    glow = art.filter(ImageFilter.GaussianBlur(5))
    glow.alpha_composite(art)
    return glow


@lru_cache(maxsize=192)
def scaled(kind,size):
    return jewel(kind).resize((size,size),Image.Resampling.LANCZOS)


def stamp(frame,kind,x,y,size,alpha):
    size=max(4,round(size/4)*4)
    sprite=scaled(kind,size)
    mask=sprite.getchannel('A')
    if alpha<.99:
        mask=mask.point(lambda v: round(v*max(0,alpha)))
    frame.paste(sprite,(round(x-size/2),round(y-size/2)),mask)


# Render light at half resolution on just the lower stage. The original scene
# supplies the shadows, while the additive pass makes the bloom catch on the floor.
STAGE_TOP = 674
STAGE_END = 1154
PALETTES = {
    'pearl': ((33, 209, 255), (170, 118, 255)),
    'heart': ((255, 63, 159), (255, 144, 118)),
    'parcel': ((255, 184, 54), (152, 83, 255)),
}


def ease(value):
    value=max(0,min(1,value))
    return 1-(1-value)**3


def stage_light(frame,kind,t,cx,side,alpha):
    main,accent=PALETTES[kind]
    lamp=Image.new('RGB',(231,240))
    pen=ImageDraw.Draw(lamp)
    x=cx/2
    floor=214
    impact=ease((t-.65)/.45)
    level=.28+.72*impact
    def tint(color,strength):
        return tuple(round(v*strength*alpha) for v in color)

    # Fan of moving spotlights and a foreshortened pair of floor rings.
    for i in range(7):
        a=-1.05+i*.35+.12*math.sin(t*1.8)
        reach=(85+14*math.sin(i+t))*(.45+.55*impact)
        end=x+math.sin(a)*reach,floor-math.cos(a)*reach
        pen.polygon([(x-3,floor), (end[0]-4,end[1]), (end[0]+4,end[1]), (x+3,floor)],
                    fill=tint(accent if i%2 else main,.20*level))
    for i in range(2):
        phase=(t*.70+i*.5)%1
        w=(36+74*phase)*ease(t/.38)
        h=4+w*.14
        pen.ellipse((x-w,floor-h,x+w,floor+h),outline=tint(main,(1-phase)*.85),width=2)
    # Comets peel away from the impact point. Some leave the stage sideways.
    for i in range(22):
        age=t-.7-(i//11)*1.28-(i%3)*.035
        if not 0<age<1.15:continue
        angle=math.pi*(.08+.84*((i*.618)%1))
        vx=side*math.cos(angle)*(77+(i%4)*13)
        vy=-math.sin(angle)*(78+(i%5)*14)
        def point(a):
            return (x+vx*a, floor-64+vy*a+27*a*a)
        tail=point(max(0,age-.13));head=point(age)
        pen.line((tail,head),fill=tint(main if i%2 else accent,(1-age/1.2)*.95),width=2)
        pen.point(head,fill=tint((255,250,230),1-age/1.2))
    bloom=ImageChops.add(lamp,lamp.filter(ImageFilter.GaussianBlur(3.6)))
    bloom=bloom.resize((462,STAGE_END-STAGE_TOP),Image.Resampling.BILINEAR)
    box=(0,STAGE_TOP,462,STAGE_END)
    stage=frame.crop(box)
    frame.paste(ImageChops.add(stage,bloom),box)


def draw_gift(frame,kind,elapsed,seed):
    if kind not in PALETTES or not 0<elapsed<DURATION:
        return
    t=elapsed
    alpha=min(1,t/.22,(DURATION-t)/.65)
    side=1 if seed%2 else -1
    cx=231+side*54
    y=1028+33*(1-ease(t/.52))+5*math.sin(t*3.5)
    lift=ease((t-.57)/.8)
    pulse=math.exp(-3*max(0,t-.75))*math.sin(8*max(0,t-.75))
    stage_light(frame,kind,t,cx,side,alpha)

    if kind=='pearl':
        stamp(frame,'shell',cx,y,192+16*pulse,alpha)
        py=y-12-130*lift
        # Two tilted strings of orbiting pearls weave in front of and behind the gem.
        for layer in (-1,1):
            for i in range(16):
                a=t*2+i*math.tau/16
                if (math.sin(a)>0)!=(layer==1):continue
                dx=90*math.cos(a)*lift
                dy=20*math.sin(a)-side*dx*.25
                stamp(frame,'pearl' if i%4 else 'star',cx+dx,py+dy,
                      (12 if i%4 else 25)*(.8+.2*math.sin(a)),alpha*lift)
            if layer==-1:stamp(frame,'pearl',cx,py,128+22*pulse,alpha)
    elif kind=='heart':
        # Satellites form a double helix around a large, beating crystal.
        for i in range(12):
            age=t-i*.18
            if 0<age<1.85:
                a=age*3.1+(i%2)*math.pi
                stamp(frame,'heart',cx+side*math.cos(a)*(48+age*43),y-20-age*145,
                      34+21*(1+math.sin(a)),alpha*min(1,age*4,(1.85-age)*3))
        beat=max(0,math.sin((t-.46)*math.tau*1.6))**3
        stamp(frame,'heart',cx,y-45-44*lift,(130+36*beat)*ease(t/.45),alpha)
    else:
        # The lid jumps on the first beat; a fountain of gold and violet foil follows.
        stamp(frame,'box',cx,y,195+15*pulse,alpha)
        stamp(frame,'lid',cx+side*48*lift,y-31-143*lift,192,alpha)
        pen=ImageDraw.Draw(frame,'RGBA')
        for i in range(36):
            age=t-.7-(i//12)*.70
            if not 0<age<1.55:continue
            vx=((i*.618+seed%13/13)%1-.5)*240
            vy=156+(i%7)*17
            px=cx+vx*age;py=y-55-vy*age+82*age*age
            w=2+4*abs(math.cos(t*8+i))
            color=((255,205,97),(207,139,255),(255,247,206))[i%3]
            pen.polygon([(px-w,py-4),(px+w,py-6),(px+w+2,py+4),(px-w+1,py+6)],
                        fill=(*color,round(235*alpha*min(1,age*5,(1.55-age)*3))))
    for i in range(18):
        age=t-.66-(i//6)*.82-(i%3)*.065
        if 0<age<1.4:
            angle=math.pi*(.11+.78*((i*.618+seed%17/17)%1))
            dx=math.cos(angle)*age*112
            dy=-math.sin(angle)*age*168+24*age**2
            stamp(frame,'star',cx+dx,y-72+dy,15+18*math.sin(math.pi*age/1.4),
                  alpha*math.sin(math.pi*age/1.4))
