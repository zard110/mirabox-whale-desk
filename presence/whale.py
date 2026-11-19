"""Local, motion-gated owner welcome. No video or face images are persisted."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import cv2
import numpy as np
from tv_feed import TVFeed
from maid_events import Announcer, ProfileLearning

ROOT = Path(__file__).resolve().parent
STATE = Path.home()/'.local/state/whale-presence'
OWNER = STATE/'owner.npy'
LATCH = STATE/'visit.json'
CAMERA = os.environ.get('WHALE_CAMERA', '/dev/video0')

def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value))
    temp.replace(path)

def notify(message):
    subprocess.run(['notify-send','-a','鲸娘','鲸娘',message],check=False)

class Vision:
    def __init__(self):
        self.cheap=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
        self.profile=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_profileface.xml')
        self.det=None
        self.embed=None
        self.last=None
        self.until=0
        self.next_edges=0

    def motion(self,frame,now):
        gray=cv2.cvtColor(cv2.resize(frame,(160,120)),cv2.COLOR_BGR2GRAY)
        small=cv2.GaussianBlur(gray,(5,5),0).astype(np.int16)
        triggered=False
        if self.last is not None:
            diff=small-self.last
            changed=np.abs(diff-np.median(diff))>12
            triggered=np.count_nonzero(changed)>50
        self.last=small
        if triggered:self.until=now+3
        return now<self.until

    def candidates(self,frame):
        gray=cv2.equalizeHist(cv2.cvtColor(cv2.resize(frame,(320,240)),cv2.COLOR_BGR2GRAY))
        result=[]
        for classifier,image,mirrored,label in [(self.cheap,gray,False,'front'),(self.profile,gray,False,'side'),(self.profile,cv2.flip(gray,1),True,'side')]:
            for x,y,w,h in classifier.detectMultiScale(image,1.12,5,minSize=(27,27)):
                box=(int(320-x-w if mirrored else x),int(y),int(w),int(h))
                if not any(overlap(box,old)>.32 for old,_ in result):result.append((box,label))
        return result

    def faces(self,frame,threshold=.85,identify=True):
        self.frontal=[]
        self.boxes=[]
        if self.det is None:
            self.det=cv2.FaceDetectorYN.create(str(ROOT/'models/face_detection_yunet_2023mar.onnx'),'',(640,480),.85)
            self.embed=cv2.FaceRecognizerSF.create(str(ROOT/'models/face_recognition_sface_2021dec.onnx'),'')
        self.det.setInputSize((frame.shape[1],frame.shape[0]))
        self.det.setScoreThreshold(threshold)
        _,rows=self.det.detect(frame)
        detections=list(rows) if rows is not None else []
        now=time.monotonic()
        if threshold<.8 and (not detections or (len(detections)==1 and now>=self.next_edges)):
            self.next_edges=now+1.5
            height,width=frame.shape[:2];span=int(width*.62)
            for left in (0,width-span):
                crop=cv2.resize(frame[:,left:left+span],None,fx=1.5,fy=1.5)
                self.det.setInputSize((crop.shape[1],crop.shape[0]));_,extra=self.det.detect(crop)
                for row in ([] if extra is None else extra):
                    row=row.copy();row[:14]/=1.5;row[0]+=left;row[4:14:2]+=left
                    if not any(overlap(row[:4],old[:4])>.35 for old in detections):detections.append(row)
        features=[]
        for row in detections:
            if min(row[2:4])<(52 if threshold>=.85 else 24):continue
            if identify:
                face=self.embed.alignCrop(frame,row)
                vector=self.embed.feature(face).flatten()
                features.append(vector/np.linalg.norm(vector))
            self.boxes.append(tuple(float(v)*scale for v,scale in zip(row[:4],(320/frame.shape[1],240/frame.shape[0])*2)))
            eye=row[6:8]-row[4:6]
            yaw=abs(float(np.dot(row[8:10]-(row[4:6]+row[6:8])/2,eye)))/max(1,float(eye@eye))
            self.frontal.append('looking' if yaw<.19 else 'working' if yaw>.29 else None)
        return features

def overlap(a,b):
    x,y,w,h=a;xx,yy,ww,hh=b
    area=max(0,min(x+w,xx+ww)-max(x,xx))*max(0,min(y+h,yy+hh)-max(y,yy))
    return area/max(1,w*h+ww*hh-area)

class Visitors:
    """Follow distinct detector boxes between identity checks."""
    def __init__(self):
        self.boxes=[]
        self.pending=[]
        self.recent=[]
        self.owner_visible=False
        self.seen=-100.

    def update(self,now,faces,owner,unfamiliar,identified):
        prior=[(old,at) for old,at in self.recent if now-at<5 and
               (owner is None or overlap(old,owner)<=.10)]
        pending=self.pending if now-self.seen<5 else []
        self.seen=now
        self.boxes=[]
        self.pending=[]
        self.owner_visible=owner is not None and any(overlap(owner,box)>.40 for box in faces)
        for i,box in enumerate(faces):
            if owner is not None and overlap(owner,box)>.10:
                continue
            if self.owner_visible or any(overlap(old,box)>.35 for old,_ in prior):
                self.boxes.append(box)
                continue
            hits=max((n for old,n in pending if overlap(old,box)>.35),default=0)
            if i in unfamiliar:
                hits+=1
            elif identified:
                hits=0
            if hits>=3:
                self.boxes.append(box)
            elif hits:
                self.pending.append((box,hits))
        self.recent=[(old,at) for old,at in prior if not any(overlap(old,b)>.35 for b in self.boxes)]
        self.recent.extend((box,now) for box in self.boxes)

class OwnerTrack:
    def __init__(self):
        self.box=None;self.seen=-100.;self.pose='unknown';self.pending=None;self.since=0;self.last_frontal=-100.

    def update(self,now,candidates,match=None,rejected=()):
        hint=None
        clear_frontal=False
        if match is not None:
            self.box,hint=match;self.seen=now
            clear_frontal=hint=='looking'
        elif self.box is not None:
            nearby=[(box,kind) for box,kind in candidates if overlap(self.box,box)>.20]
            if now-self.seen>5 or any(overlap(self.box,box)>.20 for box in rejected) or len(nearby)>1:
                self.box=None;self.pose='unknown';self.pending=None
            elif len(nearby)==1:
                self.box,kind=nearby[0];self.seen=now
                clear_frontal=kind=='looking'
                if kind=='profile' or (kind=='side' and now-self.last_frontal>2):hint='working'
                elif clear_frontal or (kind=='front' and self.pending=='looking'):hint='looking'
        if clear_frontal:
            self.last_frontal=now
            self.pose=self.pending='looking'
            self.since=now
        if hint and hint!=self.pending:self.pending=hint;self.since=now
        if hint and hint==self.pending and now-self.since>=1:self.pose=hint
        return self.pose

def display_posture(pose, owner_visible, present, usable, occupied, guests_only):
    if owner_visible:
        return 'present' if pose=='unknown' else pose
    if not usable:
        return 'unknown'
    if not present:
        return 'away'
    if guests_only:
        return 'guests_only'
    return 'unrecognized' if occupied else 'no_face'


def usable_exposure(frame):
    gray = cv2.cvtColor(frame[::8, ::8], cv2.COLOR_BGR2GRAY)
    dark, light = np.percentile(gray, (5, 95))
    return light >= 30 and dark <= 235 and light - dark >= 18


class Visit:
    # Count time between consecutive full detector scans, never across a camera gap.
    probe_interval = 4
    max_scan_gap = 9
    def __init__(self,present):
        self.present=present
        self.empty_since = None
        self.quiet_since = None
        self.last_scan = None
        self.empty_scans = 0
        self.hits=0
        self.last_hit=-100

    def observe_scan(self, now, occupied, usable, moving):
        interrupted = self.last_scan is None or now - self.last_scan > self.max_scan_gap
        self.last_scan = now
        if interrupted or occupied or not usable:
            self.empty_since = self.quiet_since = None
            self.empty_scans = 0
        if occupied or not usable:
            return
        self.empty_scans += 1
        if self.empty_since is None:
            self.empty_since = now
        if moving:
            self.quiet_since = None
        elif self.quiet_since is None:
            self.quiet_since = now
        quiet = self.quiet_since is not None and now - self.quiet_since >= 24
        if self.empty_scans >= 5 and (quiet or now - self.empty_since >= 180):
            self.present = False

    def step(self,now,is_owner):
        if is_owner:
            self.hits=1 if now-self.last_hit>4 else self.hits+1
            self.last_hit=now
        elif is_owner is False or now-self.last_hit>4:self.hits=0
        if self.hits>=3 and not self.present:
            self.present=True
            return True
        return False

def read_frame(cam):
    ok,frame=cam.read()
    if not ok or frame is None:raise RuntimeError('摄像头没有返回画面')
    return frame

def enroll(cam,vision):
    notify('请独自面对摄像头，保持几秒，然后轻轻转头。')
    deadline=time.monotonic()+40
    vectors=[]
    while time.monotonic()<deadline:
        frame=read_frame(cam)
        features=vision.faces(frame)
        if len(features)!=1:vectors.clear()
        else:
            vec=features[0]
            if vectors and float(vectors[0]@vec)<.52:vectors.clear()
            vectors.append(vec)
            if len(vectors)>=8:
                temp=OWNER.with_suffix('.tmp')
                with temp.open('wb') as fp:np.save(fp,np.stack(vectors),allow_pickle=False)
                temp.replace(OWNER)
                (STATE/'owner-side.npy').unlink(missing_ok=True)
                save(LATCH,True)
                print('已录入：8 个一致的人脸特征；未保存图像。',flush=True)
                notify('主人已录入。下次离开桌前再回来，我会问候一次。')
                return
        time.sleep(.28)
    raise RuntimeError('未取得连续清晰的单人正脸；未改动主人档案')

def watch(cam,vision):
    tv=TVFeed()
    owner=np.load(OWNER,allow_pickle=False)
    visit=Visit(json.loads(LATCH.read_text()) if LATCH.exists() else True)
    next_check=since=next_match=0;counts=[0,0,0]
    track=OwnerTrack();has_face=False;posture='unknown'
    announcer=Announcer();learning=ProfileLearning(STATE);last_face=-100;next_empty_probe=0
    confirm_until=calibrate_until=0;observed_faces=0
    detected=[]
    visitors=Visitors()
    published=None
    usable=False
    next_identity_probe=0
    while True:
        frame=read_frame(cam);now=time.monotonic();active=vision.motion(frame,now);counts[0]+=1
        if now>=next_check:
            candidates=vision.candidates(frame) if active or visit.present else []
            previous=visit.present
            owner_found=False;match=None;rejected=[]
            scanned=False;unfamiliar=[];identity_observed=False
            empty_probe=(visit.present or visit.last_scan is None) and now>=next_empty_probe
            if (active or empty_probe or now-last_face<5) and now>=next_match:
                scanned=True
                counts[2]+=1
                identify=active or now<confirm_until or (not len(learning.side) and now<calibrate_until)
                if detected and not visitors.owner_visible and now>=next_identity_probe:
                    identify=True
                if identify:
                    next_identity_probe=now+4
                faces=vision.faces(frame,.64,identify=identify)
                observed_faces=len(vision.boxes)
                if observed_faces and not detected and not identify:
                    confirm_until=now+5
                detected=list(vision.boxes)
                identity_observed=identify and bool(faces)
                front_scores=[float(np.sort(owner@vec)[-3]) for vec in faces]
                matches=[i for i,vec in enumerate(faces) if front_scores[i]>=.48 or (len(learning.side)>=3 and np.count_nonzero(learning.side@vec>=.52)>=3)]
                if identify:learning.update(now,faces,vision.boxes,vision.frontal,front_scores,overlap)
                if active and len(matches)==1 and len(faces)==1 and vision.frontal[0]=='looking' and front_scores[0]>=.52:
                    calibrate_until=now+18
                if vision.boxes:
                    last_face=now
                    for box,hint in zip(vision.boxes,vision.frontal):
                        candidates=[(b,k) for b,k in candidates if overlap(b,box)<.32]
                        candidates.append((box,{'working':'profile','looking':'looking'}.get(hint,'uncertain')))
                owner_found=bool(matches)
                next_match=now+(.65 if not visit.present or learning.box is not None or track.pose=='unknown' else 1.8)
                next_empty_probe=now+visit.probe_interval
                if matches:
                    index=matches[0];match=(vision.boxes[index],vision.frontal[index])
                rejected=[vision.boxes[i] for i in range(len(faces)) if i not in matches and vision.frontal[i]=='looking']
                unfamiliar=[i for i in range(len(faces)) if min(vision.boxes[i][2:])>=24 and vision.frontal[i]=='looking' and i not in matches and front_scores[i]<.30 and (not len(learning.side) or max(learning.side@faces[i])<.40)]
                if unfamiliar and not visitors.boxes:confirm_until=now+5
            # Haar proposals can follow a confirmed face, but cannot establish occupancy.
            has_face=bool(detected) and now-last_face<5
            candidates=[(box,kind) for box,kind in candidates if has_face and
                        any(overlap(box,face)>.20 for face in detected)]
            posture=track.update(now,candidates,match,rejected)
            owner_box=track.box if now-track.seen<2.5 else None
            if scanned:
                visitors.update(now,detected,owner_box,unfamiliar,identity_observed)
                only_guests=bool(detected) and len(visitors.boxes)==len(detected)
                usable=bool(detected) or usable_exposure(frame)
                visit.observe_scan(now, bool(detected) and not only_guests, usable, active and not only_guests)
            guest_boxes=visitors.boxes if has_face and now-visitors.seen<5 else []
            counts[1]+=int(active or visit.present)
            greet=visit.step(now,owner_found if identity_observed else None)
            if previous!=visit.present:save(LATCH,visit.present)
            if greet:
                print('主人返回 · 本次问候一次',flush=True)
            visitor_scene=None
            if guest_boxes:
                visitor_scene='visitor_here' if visitors.owner_visible else 'visitor_unsure' if visit.present else 'visitor_away'
            announcer.observe(now,posture,greet,previous and not visit.present,visitor_scene)
            visible=has_face and visitors.owner_visible and owner_box is not None
            shown=display_posture(posture,visible,visit.present,usable,has_face,
                                  bool(guest_boxes) and len(guest_boxes)==len(detected))
            display_boxes=list(candidates)
            if has_face and now-last_face<2.5:
                for box in detected:
                    if not any(overlap(box,b)>.32 for b,_ in display_boxes):
                        display_boxes.append((box,'tracked'))
            tv.observe(now,display_boxes,owner_box,guest_boxes,overlap,shown)
            next_check=now+(.45 if active else 2)
        if shown!=published or now-since>=1.5:
            published=shown
            save(STATE/'status.json',dict(time=int(time.time()),present=visit.present,posture=shown,seat_occupied=has_face,owner_visible=visible,guest_count=len(guest_boxes),side_templates=len(learning.side),last_scan_faces=observed_faces,empty_scans=visit.empty_scans,frames=counts[0],cheap_checks=counts[1],vision_checks=counts[2]))
            since=now
        tv.send(frame,time.monotonic())
        time.sleep(.14)

def main():
    os.umask(0o077);STATE.mkdir(mode=0o700,parents=True,exist_ok=True);cv2.setNumThreads(1)
    mode=sys.argv[1]
    if mode=='watch' and not OWNER.exists():raise SystemExit('请先录入主人')
    cam=cv2.VideoCapture(CAMERA,cv2.CAP_V4L2)
    if not cam.isOpened():raise RuntimeError('无法打开内置摄像头')
    try:
        cam.set(cv2.CAP_PROP_FRAME_WIDTH,640);cam.set(cv2.CAP_PROP_FRAME_HEIGHT,480);cam.set(cv2.CAP_PROP_BUFFERSIZE,1)
        for _ in range(6):read_frame(cam)
        {'enroll':enroll,'watch':watch}[mode](cam,Vision())
    finally:cam.release()

if __name__=='__main__':main()
