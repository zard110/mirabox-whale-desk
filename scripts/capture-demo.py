"""Render documentation from the shipping dashboard without opening a camera or reading an account."""
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'versions/storm-c11'))
import dashboard
import owner_strip
import subtitles
from storm import Renderer


def capture():
    out = root / 'docs/media'
    out.mkdir(parents=True, exist_ok=True)
    with patch.object(dashboard, 'UsageStatus') as usage:
        usage.return_value.sample.return_value = {}
        metrics = dashboard.Metrics()
    for _ in range(8):
        values = metrics.sample()
        time.sleep(.12)

    states = [('typing', '工作 · 打字'), ('dancing', '空闲 · 跳舞'), ('slacking', '恢复 · 摸鱼')]
    font = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc', 16, index=2)
    renderers = []
    now = datetime.now()
    with tempfile.TemporaryDirectory() as temp:
        # Keep live speech, owner state and camera frames out of published images.
        subtitles.EVENT = Path(temp) / 'no-event'
        owner_strip.STATUS = Path(temp) / 'no-status'
        for mode, _ in states:
            renderer = Renderer()
            renderer.update(values, 72, mode, {'codex': mode == 'typing', 'deepseek': False}, now)
            renderers.append(renderer)
        still = renderers[1].full(renderers[1].hero('dancing', 1.25), now, elapsed=1.25)
        still.save(out / 'dashboard.png')
        frames = []
        for tick in range(36):
            seconds = tick / 12
            sheet = Image.new('RGB', (546, 365), '#11162e')
            for j, ((mode, label), renderer) in enumerate(zip(states, renderers)):
                hero = renderer.hero(mode, seconds)
                image = hero.crop((0, 370, 462, 1240)).resize((178, 335), Image.Resampling.LANCZOS)
                sheet.paste(image, (j * 182 + 2, 30))
                ImageDraw.Draw(sheet).text((j * 182 + 91, 15), label, font=font, fill='#ffeed8', anchor='mm')
            frames.append(sheet)
        frames[0].save(out / 'modes.gif', save_all=True, append_images=frames[1:], duration=83, loop=0)


if __name__ == '__main__':
    capture()
