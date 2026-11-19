import unittest
import numpy as np
from unittest.mock import Mock, patch
from pathlib import Path
import json
import tempfile
import whale
from whale import Vision, Visit, OwnerTrack, Visitors, overlap
from maid_events import Announcer

class PresenceTest(unittest.TestCase):
    def test_working_with_separate_visitor_after_long_side_view(self):
        track=OwnerTrack()
        visitors=Visitors()
        owner=(45,68,36,51)
        guest=(210,64,32,48)
        other=(140,45,23,35)
        track.update(0,[],(owner,None))
        visitors.update(0,[owner,guest,other],track.box,[],False)
        self.assertTrue(visitors.owner_visible)
        self.assertEqual(visitors.boxes,[guest,other])
        for tick in range(1,65):
            track.update(tick,[(owner,'side')])
            visitors.update(tick,[guest,owner,other],track.box,[],False)
            self.assertEqual(visitors.boxes,[guest,other])
        self.assertEqual(track.pose,'working')
        visitors.update(65,[guest],track.box,[],False)
        self.assertFalse(visitors.owner_visible)
        self.assertEqual(visitors.boxes,[guest])
        visitors.update(66,[],None,[],False)
        self.assertEqual(visitors.boxes,[])
        visitors.update(68,[guest],None,[],False)
        self.assertEqual(visitors.boxes,[guest])
        visitors.update(75,[guest],None,[0],True)
        self.assertEqual(visitors.boxes,[])
        visitors.update(76,[guest],None,[0],True)
        visitors.update(77,[guest],None,[0],True)
        self.assertEqual(visitors.boxes,[guest])
        visitors.update(78,[guest],guest,[],True)
        self.assertEqual(visitors.boxes,[])

    def test_visitor_caption_rotation_context_audio_and_departure(self):
        import maid_events
        with tempfile.TemporaryDirectory() as tmp, patch.object(maid_events,'STATE',Path(tmp)):
            a=Announcer()
            now=5.
            def next_caption(scene):
                nonlocal now
                now=max(now,a.free)+.1
                # The camera keeps observing the visitor while the current caption scrolls.
                for tick in np.arange(a.last_visitor+1,now,1) if a.last_visitor>=0 else []:
                    if tick<a.free:a.observe(tick,'unknown',False,False,scene)
                a.observe(now,'unknown',False,False,scene)
                return json.loads((Path(tmp)/'speech-event.json').read_text())
            first=next_caption('visitor_here')
            self.assertTrue(first['audio'])
            for scene,options in a.visitor_captions.items():
                events=[next_caption(scene) for _ in range(len(options)+1)]
                self.assertTrue(all(e['scene']==scene and not e['audio'] for e in events))
                self.assertEqual({e['text'] for e in events[:-1]},set(options))
                self.assertNotEqual(events[-2]['text'],events[-1]['text'])
            last=events[-1]
            for t in range(1,25):a.observe(now+t,'unknown',False,False,None)
            self.assertEqual(json.loads((Path(tmp)/'speech-event.json').read_text())['id'],last['id'])
            a.observe(now+26,'unknown',False,False,'visitor_away')
            self.assertTrue(json.loads((Path(tmp)/'speech-event.json').read_text())['audio'])

    def test_expanded_deck_resumes_legacy_round_after_restart(self):
        import maid_events
        with tempfile.TemporaryDirectory() as tmp, patch.object(maid_events,'STATE',Path(tmp)):
            root=Path(tmp)
            (root/'phrase-bags.json').write_text(json.dumps({'visitor_here_loop':{'left':[2,5],'last':1}}))
            seen=set(range(8))-{2,5}
            a=Announcer()
            count=len(a.visitor_captions['visitor_here'])
            for turn in range(count-len(seen)):
                if turn==9:
                    a=Announcer()
                a.greeted_visitor=True
                a.publish('visitor_here',turn*10)
                event=json.loads((root/'speech-event.json').read_text())
                index=int(event['key'].split('-')[-1])
                self.assertNotIn(index,seen)
                seen.add(index)
            self.assertEqual(seen,set(range(count)))

    def test_front_facing_owner_and_multiple_visitors_share_one_scan(self):
        track=OwnerTrack()
        v=Visitors()
        feed=whale.TVFeed()
        box=(50,65,40,50)
        guests=[(155,70,20,32),(215,60,36,45)]
        try:
            track.update(0,[],(box,'working'))
            self.assertEqual(track.update(2,[(box,'profile')]),'working')
            # Identity follows the standing track while the detector reports a frontal face.
            candidates=[(box,'looking')]+[(g,'uncertain') for g in guests]
            pose=track.update(3,candidates)
            self.assertEqual(pose,'looking')
            v.update(3,[b for b,_ in candidates],track.box,[],False)
            feed.observe(3,candidates,track.box,v.boxes,overlap,pose)
            self.assertEqual([row[-1] for row in feed.boxes],['owner','guest','guest'])
            self.assertEqual(feed.posture,'looking')
            for now in (3.5,4.6):
                self.assertEqual(track.update(now,[(box,'side')]),'looking')
            self.assertEqual(track.update(5,[(box,'profile')]),'looking')
            self.assertEqual(track.update(6.2,[(box,'profile')]),'working')
            self.assertEqual(track.update(6.5,[],(box,'looking')),'looking')
        finally:
            feed.socket.close()

    def test_owner_turns_to_main_monitor_then_back(self):
        track=OwnerTrack();visit=Visit(True);box=(100,70,60,65)
        front=[(box,'front')];side=[((109,72,58,63),'side')]
        track.update(0,front,(box,'looking'))
        self.assertEqual(track.update(2,front),'looking')
        self.assertEqual(track.update(3,side),'looking')
        for now in range(5,150,2):
            self.assertEqual(track.update(now,side),'working')
            self.assertFalse(visit.step(now,False))
        self.assertTrue(visit.present)
        track.update(150,front,(box,'looking'))
        self.assertEqual(track.update(152,front),'looking')
        self.assertEqual(track.update(158,[]),'unknown')
        self.assertEqual(track.update(160,side),'unknown')

    def test_unmatched_frontal_face_drops_previous_owner(self):
        box=(80,60,50,50);track=OwnerTrack();face=[(box,'front')]
        track.update(1,face,(box,'looking'))
        self.assertEqual(track.update(3,face),'looking')
        self.assertEqual(track.update(4,face,rejected=[box]),'unknown')
    def test_idle_and_light_change_do_not_open_motion_gate(self):
        vision=Vision()
        blank=np.zeros((480,640,3),np.uint8)
        self.assertFalse(vision.motion(blank,10))
        lit=blank+52
        self.assertFalse(vision.motion(lit,11))
        lit[80:170,50:120]=145
        self.assertTrue(vision.motion(lit,12))
        self.assertFalse(vision.motion(lit,16))
        self.assertIsNone(vision.det)

    def test_one_greeting_per_visit(self):
        visit=Visit(True)
        for sec in range(0, 181, 4):
            visit.observe_scan(sec, occupied=False, usable=True, moving=True)
            self.assertEqual(visit.present, sec < 180)
        for sec in (181,182):
            self.assertFalse(visit.step(sec,True))
        self.assertFalse(visit.step(183,False))
        self.assertEqual([visit.step(t,True) for t in range(184,191)],[False,False,True,False,False,False,False])

    def test_side_faces_dark_frames_and_camera_gaps_interrupt_vacancy(self):
        visit=Visit(True)
        for sec in range(0, 300, 4):
            visit.observe_scan(sec, occupied=sec%20==0, usable=True, moving=False)
            self.assertTrue(visit.present)
        for sec in range(300, 400, 4):
            visit.observe_scan(sec, occupied=False, usable=sec%20!=0, moving=False)
            self.assertTrue(visit.present)
        for sec in (450, 465, 480, 500):
            visit.observe_scan(sec, occupied=False, usable=True, moving=False)
            self.assertTrue(visit.present)
        for value in (0, 12, 250):
            self.assertFalse(whale.usable_exposure(np.full((480,640,3), value, np.uint8)))

    def test_owner_box_and_bottom_status_agree_before_pose_settles(self):
        box=(30,70,35,55)
        vector=np.array([1.,0.])
        vision=Mock()
        vision.motion.return_value=True
        vision.candidates.return_value=[]
        vision.boxes=[box]
        now=[0.]
        def detect(*args, **kwargs):
            vision.frontal=[None if now[0]<4 else 'looking' if now[0]<8 else 'working']
            return [vector]
        vision.faces.side_effect=detect
        def advance(seconds):
            now[0]+=seconds
            if now[0]>12:
                raise StopIteration
        frame=np.zeros((480,640,3),np.uint8)
        cam=Mock()
        cam.read.return_value=True,frame
        feed=whale.TVFeed()
        displayed=[]
        def check_frame(*args):
            status=json.loads((root/'status.json').read_text())
            self.assertEqual(feed.posture,status['posture'])
            if feed.boxes:
                self.assertEqual(feed.boxes[0][-1],'owner')
                displayed.append(feed.posture)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                np.save(root/'owner.npy',np.tile(vector,(8,1)))
                with patch.multiple(whale,STATE=root,OWNER=root/'owner.npy',LATCH=root/'visit.json'), \
                     patch.object(whale.time,'monotonic',side_effect=lambda:now[0]), \
                     patch.object(whale.time,'sleep',side_effect=advance), \
                     patch.object(whale,'TVFeed',return_value=feed),patch.object(feed,'send',side_effect=check_frame), \
                     patch.object(Announcer,'publish'):
                    with self.assertRaises(StopIteration):
                        whale.watch(cam,vision)
        finally:
            feed.socket.close()
        self.assertEqual(list(dict.fromkeys(displayed)),['present','looking','working'])

    def test_static_unmatched_face_is_rechecked_and_confirmed_guest_can_remain_after_departure(self):
        # For the first 12 seconds the face is a side profile; it then becomes identifiable.
        elapsed=[0.]
        owner=np.array([1.,0.])
        other=np.array([0.,1.])
        cam=Mock()
        cam.read.return_value=True,np.zeros((480,640,3),np.uint8)
        vision=Mock()
        vision.motion.return_value=False
        vision.candidates.return_value=[]
        vision.boxes=[(80,65,26,41)]
        def detect(frame,threshold,identify):
            vision.frontal=['working' if elapsed[0]<12 else 'looking']
            return [other] if identify else []
        vision.faces.side_effect=detect
        def advance(seconds):
            elapsed[0]+=seconds
            if elapsed[0]>65:
                raise StopIteration
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            np.save(root/'owner.npy',np.tile(owner,(8,1)))
            with patch.multiple(whale,STATE=root,OWNER=root/'owner.npy',LATCH=root/'visit.json'), \
                 patch.object(whale.time,'monotonic',side_effect=lambda:elapsed[0]), \
                 patch.object(whale.time,'sleep',side_effect=advance), \
                 patch.object(whale,'TVFeed') as tv,patch.object(whale,'Announcer') as ann:
                with self.assertRaises(StopIteration):
                    whale.watch(cam,vision)
                states=[c.args[-1] for c in tv.return_value.observe.call_args_list]
                self.assertEqual(list(dict.fromkeys(states)),['unrecognized','guests_only','away'])
                self.assertTrue(any(c.args[-1]=='visitor_away' for c in ann.return_value.observe.call_args_list))
                self.assertEqual(sum(c.args[3] for c in ann.return_value.observe.call_args_list),1)

    def test_watch_empty_scene_despite_haar_proposals(self):
        # Use the deployed detector on a textured empty scene, with a false Haar box every poll.
        frame=np.zeros((480,640,3), np.uint8)
        frame[:]=np.arange(640, dtype=np.uint16)[None,:,None]//3
        cam=Mock()
        cam.read.return_value=(True,frame)
        vision=Vision()
        vision.candidates=Mock(return_value=[((45,60,42,60),'front')])
        elapsed=[0.]
        def advance(seconds):
            elapsed[0]+=seconds
            if elapsed[0]>38:
                raise StopIteration
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            np.save(root/'owner.npy',np.zeros((8,128)))
            for expected_departures in (1,0):  # second run starts with the saved away latch
                elapsed[0]=0.
                with patch.multiple(whale,STATE=root,OWNER=root/'owner.npy',LATCH=root/'visit.json'), \
                     patch.object(whale.time,'monotonic',side_effect=lambda:elapsed[0]), \
                     patch.object(whale.time,'sleep',side_effect=advance), \
                     patch.object(whale,'TVFeed') as tv, patch.object(whale,'Announcer') as announcer:
                    announcer.return_value.guest=False
                    with self.assertRaises(StopIteration):
                        whale.watch(cam,vision)
                    status=json.loads((root/'status.json').read_text())
                    states=[c.args[-1] for c in tv.return_value.observe.call_args_list]
                    self.assertEqual(states[0],'no_face' if expected_departures else 'away')
                    self.assertEqual(status['posture'],'away')
                    self.assertFalse(status['seat_occupied'])
                    self.assertFalse(json.loads((root/'visit.json').read_text()))
                    self.assertEqual(sum(call.args[3] for call in announcer.return_value.observe.call_args_list),expected_departures)
                    self.assertTrue(all(not call.args[1] for call in tv.return_value.observe.call_args_list))
                    self.assertGreater(vision.candidates.call_count,0)
