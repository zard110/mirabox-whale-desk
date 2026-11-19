#!/usr/bin/python3
"""MiraBox D92 animated companion; live metrics and local AI activity metadata."""
import argparse
from collections import deque
from datetime import datetime
from functools import lru_cache
import io
import json
import math
import os
from pathlib import Path
import select
import signal
import struct
import time

import psutil
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
from companion import Activity, Stamina
from usage_status import UsageStatus

ROOT = Path(__file__).resolve().parent
STATE = Path.home() / '.local/state/mirabox-d92'
SIZE = (462, 1920)
from storm import Renderer, HERO, UPPER
FONT = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
RUNNING = True


def find_device():
    devices = []
    serial = os.environ.get('MIRABOX_SERIAL')
    for p in Path('/sys/class/hidraw').glob('hidraw*'):
        try:
            fields = dict(line.split('=', 1) for line in (p / 'device/uevent').read_text().splitlines() if '=' in line)
            if fields.get('HID_ID') == '0003:00005548:00001011' and (not serial or fields.get('HID_UNIQ') == serial):
                if b'\x96\x00\x04\x91' not in (p / 'device/report_descriptor').read_bytes():
                    continue
                devices.append(Path('/dev') / p.name)
        except OSError:
            pass
    if len(devices) == 1:
        return devices[0]
    if devices:
        raise RuntimeError('Multiple D92 displays detected. Set MIRABOX_SERIAL to select one.')
    raise FileNotFoundError('No compatible MiraBox D92 output interface found')


def command(word, args=b''):
    if word not in ('DIS', 'LIG', 'CONNECT'):
        raise ValueError('Unsupported command')
    return (b'CRT\0\0' + word.encode('ascii') + args).ljust(1024, b'\0')


def frame_packet(image, box=None, quality=80):
    """Volatile DRA only. Convert the logical crop to this panel's 180° mounting."""
    output = io.BytesIO()
    image.convert('RGB').transpose(Image.Transpose.ROTATE_180).save(output, 'JPEG', quality=quality, optimize=False, progressive=False, subsampling=2)
    jpeg = output.getvalue()
    if len(jpeg) > 512 * 1024:
        raise ValueError('Image too large')
    header = bytearray(32)
    header[:8] = b'CRT\0\0DRA'
    struct.pack_into('>I', header, 8, 32 + len(jpeg))
    header[12] = 0xb1
    if box is not None:
        x0, y0, x1, y1 = box
        w, h = image.size
        if (x1 - x0, y1 - y0) != (w, h) or not (0 <= x0 < x1 <= SIZE[0] and 0 <= y0 < y1 <= SIZE[1]):
            raise ValueError('Invalid partial-frame bounds')
        struct.pack_into('>HHHH', header, 13, w, h, SIZE[0] - x1, SIZE[1] - y1)
    packet = header + jpeg
    return bytes(packet).ljust(((len(packet) + 1023) // 1024) * 1024, b'\0')


def send(fd, packet):
    for offset in range(0, len(packet), 1024):
        report = b'\0' + packet[offset:offset + 1024]
        deadline = time.monotonic() + 2
        while True:
            try:
                if os.write(fd, report) != len(report):
                    raise OSError('Short HID write')
                break
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('HID write timed out')
                select.select([], [fd], [], remaining)
    time.sleep(.004)  # The D92 needs a gap between complete DRA commands.


@lru_cache(maxsize=20)
def font(size):
    return ImageFont.truetype(FONT, size)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False))
    temporary.replace(path)


def network_totals():
    counters = psutil.net_io_counters(pernic=True)
    up = psutil.net_if_stats()
    # Include inactive physical interfaces so totals mean this boot, not this connection.
    names = [n for n in counters if (Path('/sys/class/net') / n / 'device').exists()]
    if not names:
        names = [n for n in counters if n in up and up[n].isup and not n.startswith(('lo', 'docker', 'veth', 'br-', 'tun', 'tap', 'virbr'))]
    return (tuple(sorted(names)), sum(counters[n].bytes_recv for n in names), sum(counters[n].bytes_sent for n in names))


class Metrics:
    def __init__(self):
        self.history = deque([0.0] * 35, maxlen=35)
        self.down_history = deque([0.0] * 90, maxlen=90)
        self.up_history = deque([0.0] * 90, maxlen=90)
        self.net = network_totals()
        self.at = time.monotonic()
        self.usage = UsageStatus(Path.home(), STATE)
        psutil.cpu_percent()

    def sample(self):
        now = time.monotonic()
        cpu = psutil.cpu_percent()
        self.history.append(cpu)
        mem = psutil.virtual_memory()
        net = network_totals()
        dt = max(.1, now - self.at)
        same = self.net[0] == net[0]
        down = max(0, net[1] - self.net[1]) / dt if same else 0
        upload = max(0, net[2] - self.net[2]) / dt if same else 0
        self.down_history.append(down)
        self.up_history.append(upload)
        self.at, self.net = now, net
        return {'cpu': cpu, 'temperature': cpu_temperature(), 'memory': mem.percent,
                'memory_gb': (mem.total - mem.available) / 2**30, 'memory_total_gb': mem.total / 2**30,
                'down': down, 'up': upload, 'total_upload': net[2], 'total_download': net[1],
                'history': list(self.history), 'down_history': list(self.down_history),
                'up_history': list(self.up_history), 'usage': self.usage.sample()}


def cpu_temperature():
    try:
        sensors = psutil.sensors_temperatures()
        cores = sensors.get('coretemp', [])
        packages = [sensor.current for sensor in cores if 'package' in sensor.label.lower() and 0 < sensor.current < 150]
        if packages:
            return max(packages)
        for group in ('coretemp', 'k10temp', 'zenpower', 'dell_ddv'):
            values = [sensor.current for sensor in sensors.get(group, [])
                      if 0 < sensor.current < 150 and (group != 'dell_ddv' or sensor.label.upper() == 'CPU')]
            if values:
                return max(values)
    except (OSError, AttributeError):
        pass
    return None


def compact(value, suffix=''):
    if value is None:
        return '—'
    for unit, scale in [('B', 1e9), ('M', 1e6), ('K', 1e3)]:
        if value >= scale:
            return f'{value / scale:.2f}'.rstrip('0').rstrip('.') + unit + suffix
    return f'{value:.0f}' + suffix


def byte_count(value, per_second=False):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1024 or unit == 'TB':
            return f'{value:.1f} {unit}' + ('/s' if per_second else '')
        value /= 1024



def stop(*_):
    global RUNNING
    RUNNING = False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preview', type=Path)
    parser.add_argument('--mode', choices=['typing', 'dancing', 'slacking'])
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    if args.status:
        print((STATE / 'runtime.json').read_text())
        return
    STATE.mkdir(parents=True, exist_ok=True)
    stamina = Stamina(STATE / 'companion.json')
    activity = Activity(Path.home(), psutil.boot_time())
    metrics, renderer = Metrics(), Renderer()
    now = time.monotonic()
    busy = activity.sample()
    mode = args.mode or stamina.tick(0, any(busy.values()))
    renderer.update(metrics.sample(), stamina.energy, mode, busy)
    if args.preview:
        image = renderer.full(renderer.hero(mode, .7))
        image.convert('RGB').save(args.preview)
        print(f'Preview: {args.preview}; mode={mode}; stamina={stamina.energy:.1f}; bytes={len(frame_packet(image))}')
        return
    signal.signal(signal.SIGTERM, stop)
    renderer.tv.listen()
    signal.signal(signal.SIGINT, stop)
    last_tick = mode_started = now
    last_sample = now - 2
    previous_sprite = None
    next_full = next_keepalive = next_header = 0
    frames_sent, measured_fps, rate_started = 0, 0.0, now
    fd = None
    try:
        while RUNNING:
            started = time.monotonic()
            try:
                if fd is None:
                    fd = os.open(find_device(), os.O_RDWR | os.O_NONBLOCK)
                    send(fd, command('DIS'))
                    send(fd, command('LIG', bytes([0, 0, 65])))
                    next_full = next_keepalive = next_header = 0
                    print('D92 connected; live whale companion; target 24 fps', flush=True)
                if started - last_sample >= 1:
                    busy = activity.sample()
                    values = metrics.sample()
                    last_sample = started
                    next_full = 0
                old_mode = mode
                mode = args.mode or stamina.tick(started - last_tick, any(busy.values()))
                last_tick = started
                if mode != old_mode:
                    previous_sprite = renderer.scene(old_mode, started - mode_started)
                    mode_started = started
                    next_full = 0
                    print(f'Mode: {mode}; stamina={stamina.energy:.1f}; AI={busy}', flush=True)
                    stamina.save()
                previous_pose = renderer.owner_pose
                if next_full == 0:
                    renderer.update(values, stamina.energy, mode, busy)
                renderer.tv.update()
                if renderer.owner_pose != previous_pose:
                    next_full = 0
                anim = renderer.hero(mode, started - mode_started, previous_sprite)
                if started >= next_keepalive:
                    send(fd, command('CONNECT'))
                    next_keepalive = started + 2
                if started >= next_full or renderer.captions.active():
                    packet = frame_packet(renderer.full(anim,elapsed=started-mode_started))
                    next_full = started + 1
                    next_header = started + .125
                else:
                    packet = frame_packet(anim, HERO, quality=77)
                send(fd, packet)
                if started >= next_header:
                    send(fd, frame_packet(renderer.top_at(datetime.now(),started-mode_started), UPPER, quality=77))
                    next_header = started + .125
                frames_sent += 1
                if started - rate_started >= 1:
                    measured_fps = frames_sent / (started - rate_started)
                    frames_sent, rate_started = 0, started
                    atomic_json(STATE / 'runtime.json', {'time': datetime.now().isoformat(timespec='seconds'), 'mode': mode, 'energy': round(stamina.energy, 2), 'ai': busy, 'fps': round(measured_fps, 1), 'target_fps': 24, 'last_packet_bytes': len(packet), 'connected': True, 'partial_updates': True, 'header_fps_target': 8, 'ai_effect_active': any(busy.values()), 'ai_effect_style': 'storm-native-relit', 'layout_version': 11, 'tv_frames': renderer.tv.frames, 'tv_boxes': renderer.tv.box_count, 'owner_pose': renderer.owner_pose, 'metrics': {k: v for k, v in values.items() if not k.endswith('history')}})
                if started - stamina.last_save > 5:
                    stamina.save()
                remaining = 1 / 24 - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)
            except (OSError, RuntimeError) as error:
                print(f'Waiting for D92: {error}', flush=True)
                atomic_json(STATE / 'runtime.json', {'time': datetime.now().isoformat(timespec='seconds'), 'mode': mode, 'energy': round(stamina.energy, 2), 'connected': False, 'error': str(error)})
                if fd is not None:
                    os.close(fd)
                    fd = None
                time.sleep(2)
                last_tick = time.monotonic()
    finally:
        stamina.save()
        if fd is not None:
            os.close(fd)


if __name__ == '__main__':
    main()
