import fcntl
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest
from PIL import Image
from companion import Stamina, codex_running, deepseek_running
from dashboard import frame_packet, HERO


class CompanionTest(unittest.TestCase):
    def test_complete_stamina_cycle_and_work_interrupt(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.json'
            pet = Stamina(path)
            self.assertEqual(pet.energy, 100)
            for _ in range(100):
                pet.tick(1, False)
            self.assertAlmostEqual(pet.energy, 80)
            self.assertEqual(pet.mode, 'dancing')
            for _ in range(30):
                pet.tick(1, True)
            self.assertEqual(pet.mode, 'typing')
            self.assertAlmostEqual(pet.energy, 80)
            for _ in range(300):
                pet.tick(1, False)
            self.assertAlmostEqual(pet.energy, 20)
            self.assertEqual(pet.mode, 'slacking')
            for _ in range(5):
                pet.tick(1, False)
            self.assertAlmostEqual(pet.energy, 45)
            for _ in range(20):
                pet.tick(1, True)
            self.assertEqual(pet.mode, 'typing')
            self.assertAlmostEqual(pet.energy, 45)
            pet.tick(1, False)
            self.assertEqual(pet.mode, 'slacking')
            pet.save()
            restored = Stamina(path)
            self.assertEqual(restored.idle_mode, 'slacking')
            self.assertAlmostEqual(restored.energy, pet.energy, places=4)
            for _ in range(10):
                restored.tick(1, False)
            self.assertAlmostEqual(restored.energy, 100)
            self.assertEqual(restored.mode, 'dancing')

    def test_idle_time_is_mostly_dance_with_quick_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            pet = Stamina(Path(d) / 'state.json')
            dance_seconds = rest_seconds = 0
            for _ in range(2):
                for _ in range(400):
                    self.assertEqual(pet.mode, 'dancing')
                    pet.tick(1, False)
                    dance_seconds += 1
                self.assertAlmostEqual(pet.energy, 20)
                self.assertEqual(pet.mode, 'slacking')
                for _ in range(16):
                    pet.tick(1, False)
                    rest_seconds += 1
                self.assertEqual(pet.mode, 'dancing')
                self.assertAlmostEqual(pet.energy, 100)
            self.assertGreater(dance_seconds / (dance_seconds + rest_seconds), .96)

    def test_codex_busy_completed_and_superseded_turns(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / 'history.sqlite'
            with closing(sqlite3.connect(db)) as c:
                c.execute('create table thread_turns (thread_id text, rollout_ordinal int, status text, started_at int, completed_at int)')
                c.execute("insert into thread_turns values ('a',1,'inProgress',100,null)")
                c.commit()
            self.assertTrue(codex_running(db, 50))
            self.assertFalse(codex_running(db, 50, False))
            self.assertFalse(codex_running(db, 150))
            with closing(sqlite3.connect(db)) as c:
                c.execute("insert into thread_turns values ('a',2,'completed',200,210)")
                c.commit()
            self.assertFalse(codex_running(db, 50))
            with closing(sqlite3.connect(db)) as c:
                c.execute("insert into thread_turns values ('b',1,'inProgress',220,null)")
                c.commit()
            self.assertTrue(codex_running(db, 50))
            with closing(sqlite3.connect(db)) as c:
                c.execute("update thread_turns set status='completed', completed_at=240 where thread_id='b'")
                c.commit()
            self.assertFalse(codex_running(db, 50))

    def test_deepseek_open_turn_requires_live_session_lock(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            lock = home / 'sessions/work/session-test/session.lock'
            lock.parent.mkdir(parents=True)
            lock.touch()
            cache = home / 'storages/session_projcache/sessions/session-test.json'
            cache.parent.mkdir(parents=True)
            def save(seq):
                cache.write_text(json.dumps({'record': {'rows': {'turnBoundary': {'val': {'openTurnStartSeq': seq}}}}}))
            save(0)
            self.assertFalse(deepseek_running(home))
            with lock.open('rb') as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertTrue(deepseek_running(home))
                save(None)
                self.assertFalse(deepseek_running(home))
                fcntl.flock(handle, fcntl.LOCK_UN)

    def test_partial_update_mounting_and_packet_padding(self):
        x0, y0, x1, y1 = HERO
        packet = frame_packet(Image.new('RGB', (x1 - x0, y1 - y0), '#ffaa00'), HERO)
        self.assertEqual(packet[:8], b'CRT\0\0DRA')
        self.assertEqual(len(packet) % 1024, 0)
        self.assertEqual(struct.unpack('>HHHH', packet[13:21]), (462, 1312, 0, 0))
        self.assertEqual(packet[32:34], b'\xff\xd8')
        with self.assertRaises(ValueError):
            frame_packet(Image.new('RGB', (5, 5)), HERO)


if __name__ == '__main__':
    unittest.main()
