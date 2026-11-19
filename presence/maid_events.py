import json
import random
import time
from pathlib import Path

BANK=Path(__file__).resolve().parents[1]/'maid-voice'
TIMING=json.loads((BANK/'caption-timing.json').read_text())
STATE=Path.home()/'.local/state/whale-presence'

def write(name,obj):
    file=STATE/name;temp=file.with_suffix('.tmp');temp.write_text(json.dumps(obj,ensure_ascii=False));temp.replace(file)

class Announcer:
    def __init__(self):
        self.lines=json.loads((BANK/'lines.json').read_text());self.durations=json.loads((BANK/'durations.json').read_text())
        try:self.bags=json.loads((STATE/'phrase-bags.json').read_text())
        except (ValueError,OSError):self.bags={}
        self.free=0;self.pending={};self.last_pose=None;self.pose_since=0;self.said_pose=None
        self.visitor_captions=json.loads((BANK/'visitor-captions.json').read_text())
        self.pose_spoken={}
        self.greeted_visitor=False
        self.last_visitor=-100.

    def event(self,scene,now):
        priority=4 if scene in ('return','away') else 3 if scene.startswith('visitor') else 2 if scene=='looking' else 1
        if priority==4:self.pending.clear()
        if scene=='looking':self.pending.pop(1,None)
        self.pending[priority]=(scene,now)

    def observe(self,now,pose,greet,left,visitor_scene):
        if greet:self.event('return',now)
        elif left:self.event('away',now)
        if greet or left:
            self.said_pose=None
            self.pose_spoken.clear()
        if pose!=self.last_pose:
            self.pending.pop(1,None)
            self.pending.pop(2,None)
            if self.last_pose=='unknown' and now-self.pose_since>=10:self.said_pose=None
            self.last_pose=pose;self.pose_since=now
        if not left and pose in ('looking','working') and pose!=self.said_pose:
            if now-self.pose_spoken.get(pose,float('-inf'))>=75 and (pose=='looking' or now-self.pose_since>=3):
                self.event(pose,now);self.said_pose=pose
        if now-self.last_visitor>5:
            self.greeted_visitor=False
        if visitor_scene:
            self.last_visitor=now
            self.event(visitor_scene,now)
        else:
            self.pending.pop(3,None)
        if now>=self.free:
            while self.pending:
                scene,when=self.pending.pop(max(self.pending))
                if now-when<18:self.publish(scene,now);break

    def legacy_remaining(self, bank, count):
        bag=self.bags.get(bank)
        if bag is None:
            return list(range(count))
        # The original visitor loop decks shipped with eight lines and no size.
        size=bag.get('size',8 if bank.endswith('_loop') else count)
        return list(bag['left'])+list(range(size,count))

    def draw_index(self, bank, count):
        bag=self.bags.setdefault(bank,{'left':list(range(count)), 'last':None, 'size':count})
        left=self.legacy_remaining(bank,count)
        if not left:
            left=list(range(count))
        recent=bag.get('recent',[bag['last']] if bag['last'] is not None else [])
        choices=[i for i in left if i not in recent]
        index=random.SystemRandom().choice(choices or left)
        left.remove(index)
        window=max(1,min(8,count//2))
        bag.update(left=left,last=index,size=count,recent=(recent+[index])[-window:])
        write('phrase-bags.json',self.bags)
        return index

    def publish(self,scene,now):
        visitor=scene.startswith('visitor_')
        repeat=visitor and self.greeted_visitor
        voice='original'
        durations=self.durations
        try:
            if (STATE/'voice-choice').read_text().strip()=='playful':
                durations=json.loads((BANK/'voices/playful/durations.json').read_text())
                voice='playful'
        except FileNotFoundError:
            pass
        if visitor and voice=='playful':
            loop=scene+'_loop'
            bank=scene+'_all'
            captions=self.visitor_captions[scene]
            count=len(captions)+len(self.lines[scene])
            if bank not in self.bags:
                # Carry the unplayed parts of both former decks into the first combined round.
                left=self.legacy_remaining(loop,len(captions))
                left.extend(len(captions)+i for i in self.legacy_remaining(scene,len(self.lines[scene])))
                recent=[]
                for old,offset in ((loop,0),(scene,len(captions))):
                    last=self.bags.get(old,{}).get('last')
                    if last is not None:
                        recent.append(offset+last)
                self.bags[bank]={'left':left,'size':count,'last':None,'recent':recent}
            index=self.draw_index(bank,count)
            if index<len(captions):
                key=f'{loop}-{index}'
                text=captions[index]
            else:
                index-=len(captions)
                key=f'{scene}-{index}'
                text=self.lines[scene][index]
        else:
            bank=scene+'_loop' if repeat else scene
            options=self.visitor_captions[scene] if repeat else self.lines[scene]
            index=self.draw_index(bank,len(options))
            key=f'{bank}-{index}'
            text=options[index]
        audio=not repeat or key in durations
        duration=durations[key] if audio else max(3.2,len(text)*.24)
        if scene in ('looking','working'):self.pose_spoken[scene]=now
        if visitor:self.greeted_visitor=True
        self.free=now+(duration+TIMING['tail_seconds'])/TIMING['scroll_speed']+TIMING['gap_seconds']
        write('speech-event.json',dict(scene=scene,key=key,voice=voice,audio=audio,gift=not repeat,text=text,duration=duration,id=time.time_ns(),at=time.time()))

class ProfileLearning:
    """Only retain a side template after a continuous front→side→verified front sequence."""
    def __init__(self,state):
        import numpy as np
        self.path=state/'owner-side.npy'
        try:self.side=np.load(self.path,allow_pickle=False)
        except (OSError,ValueError):self.side=[]
        self.box=None;self.at=-100;self.begin=0;self.pending=[]

    def update(self,now,faces,boxes,poses,front_scores,overlap):
        import numpy as np
        if len(faces)!=1:self.box=None;self.pending=[];return
        box=boxes[0];continuous=self.box is not None and now-self.at<=4 and overlap(self.box,box)>.38 and now-self.begin<25
        if not continuous:self.box=None;self.pending=[]
        if poses[0]=='looking' and front_scores[0]>=.52:
            if continuous and len(self.pending)>=3 and not len(self.side):
                self.side=np.stack(self.pending[-10:]);tmp=self.path.with_suffix('.tmp')
                with tmp.open('wb') as fp:np.save(fp,self.side,allow_pickle=False)
                tmp.replace(self.path)
            self.begin=now;self.pending=[];self.box=box
        elif continuous:
            self.box=box
            if poses[0]=='working' and (not self.pending or self.pending[-1]@faces[0]>.48):self.pending.append(faces[0].copy())
        self.at=now
