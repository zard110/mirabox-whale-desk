import json
import os
import socket
from pathlib import Path

import cv2


class TVFeed:
    def __init__(self):
        self.path=Path(os.environ.get('XDG_RUNTIME_DIR',f'/run/user/{os.getuid()}'))/'whale-d92-tv.sock'
        self.socket=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
        self.socket.setblocking(False)
        self.next=0
        self.boxes=[]
        self.updated=0
        self.posture='unknown'

    def observe(self,now,candidates,owner,guests,overlap,posture):
        self.boxes=[]
        for box,_ in candidates:
            tag='owner' if owner is not None and overlap(owner,box)>.40 else 'guest' if any(overlap(guest,box)>.40 for guest in guests) else 'pending'
            self.boxes.append([*[int(v) for v in box],tag])
        self.posture=posture
        self.updated=now

    def send(self,frame,now):
        if now<self.next:return
        self.next=now+.12
        if not self.path.exists():return
        small=cv2.resize(frame,(320,240),interpolation=cv2.INTER_AREA)
        ok,data=cv2.imencode('.jpg',small,[cv2.IMWRITE_JPEG_QUALITY,76])
        if ok:
            fresh=now-self.updated<2.5
            header=json.dumps([now,self.boxes[:12] if fresh else [],self.posture if fresh else None]).encode()
            try:self.socket.sendto(header+b'\n'+data.tobytes(),str(self.path))
            except (BlockingIOError,FileNotFoundError,ConnectionRefusedError):pass
