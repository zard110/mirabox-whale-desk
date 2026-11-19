"""Local activity detection and persistent whale stamina. Reads status metadata only."""
import fcntl
from contextlib import closing
import json
import math
import os
from pathlib import Path
import sqlite3
import time


class Stamina:
    REST_AT = 20.0
    DANCE_AT = 100.0
    DANCE_PER_SECOND = .2
    REST_PER_SECOND = 5.0

    def __init__(self, path):
        self.path = Path(path)
        self.energy = 100.0
        self.idle_mode = 'dancing'
        self.mode = 'dancing'
        self.last_save = 0.0
        try:
            saved = json.loads(self.path.read_text())
            value = float(saved['energy'])
            if math.isfinite(value):
                self.energy = max(0.0, min(100.0, value))
            if saved.get('idle_mode') in ('dancing', 'slacking'):
                self.idle_mode = saved['idle_mode']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self.mode = self.idle_mode

    def tick(self, seconds, busy):
        # Time while the service is stopped/suspended does not consume stamina.
        remaining = max(0.0, min(10.0, seconds))
        if busy:
            self.mode = 'typing'
            return self.mode
        if self.energy <= self.REST_AT:
            self.idle_mode = 'slacking'
        elif self.energy >= self.DANCE_AT:
            self.idle_mode = 'dancing'
        while remaining > 1e-9:
            if self.idle_mode == 'dancing':
                until_switch = max(0.0, (self.energy - self.REST_AT) / self.DANCE_PER_SECOND)
                spent = min(remaining, until_switch)
                self.energy -= spent * self.DANCE_PER_SECOND
                remaining -= spent
                if self.energy <= self.REST_AT + 1e-8:
                    self.energy = self.REST_AT
                    self.idle_mode = 'slacking'
            else:
                until_switch = max(0.0, (self.DANCE_AT - self.energy) / self.REST_PER_SECOND)
                spent = min(remaining, until_switch)
                self.energy += spent * self.REST_PER_SECOND
                remaining -= spent
                if self.energy >= self.DANCE_AT - 1e-8:
                    self.energy = self.DANCE_AT
                    self.idle_mode = 'dancing'
        self.energy = min(100.0, max(0.0, self.energy))
        self.mode = self.idle_mode
        return self.mode

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'energy': self.energy, 'idle_mode': self.idle_mode, 'saved_at': time.time()}))
        temporary.replace(self.path)
        self.last_save = time.monotonic()


def codex_running(database, since, host_alive=True):
    if not host_alive or not Path(database).exists():
        return False
    with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True, timeout=.15)) as connection:
        # Ignore old unfinished turns superseded by a later turn in the same chat.
        return bool(connection.execute('''SELECT EXISTS (
          SELECT 1 FROM thread_turns t
          WHERE t.status IN ('inProgress','in_progress','running')
          AND t.completed_at IS NULL AND t.started_at >= ?
          AND NOT EXISTS (SELECT 1 FROM thread_turns n
            WHERE n.thread_id=t.thread_id AND n.rollout_ordinal>t.rollout_ordinal))''', (since,)).fetchone()[0])


def locked(path):
    try:
        with Path(path).open('rb') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError:
        pass
    return False


def deepseek_running(home):
    home = Path(home)
    locks = {p.parent.name: p for p in (home / 'sessions').glob('*/*/session.lock')}
    for p in (home / 'storages/session_projcache/sessions').glob('*.json'):
        lock = locks.get(p.stem)
        if lock is None or not locked(lock):
            continue
        try:
            rows = json.loads(p.read_text())['record']['rows']
            turn = rows.get('turnBoundary', {}).get('val', {})
            if turn.get('openTurnStartSeq') is not None:
                return True
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return False


class Activity:
    def __init__(self, home, boot_time):
        self.home = Path(home)
        self.boot_time = boot_time
        self.host_alive = False
        self.next_process_check = 0
        self.last_ok = {'codex': 0, 'deepseek': 0}
        self.last_value = {'codex': False, 'deepseek': False}

    def sample(self):
        import psutil
        now = time.monotonic()
        if now >= self.next_process_check:
            self.next_process_check = now + 10
            self.host_alive = any(p.info['name'].lower() in ('codex', 'chatgpt') for p in psutil.process_iter(['name']) if p.info['name'])
        result = {}
        for key, read in [
            ('codex', lambda: codex_running(self.home / '.codex/thread_history_1.sqlite', self.boot_time, self.host_alive)),
            ('deepseek', lambda: deepseek_running(self.home / '.dsh')),
        ]:
            try:
                result[key] = read()
                self.last_value[key] = result[key]
                self.last_ok[key] = now
            except (sqlite3.Error, OSError):
                result[key] = self.last_value[key] and now - self.last_ok[key] < 10
        return result
