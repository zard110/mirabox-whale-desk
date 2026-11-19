#!/usr/bin/python3
"""选择下一次副屏语音使用的声音。"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import wave

BANK = Path(__file__).resolve().parent
STATE = Path.home() / '.local/state/whale-presence/voice-choice'
LABELS = {'playful': '机灵少女 · 俏皮萌妹', 'original': '原配音 · 柔和少女'}


def current():
    if STATE.is_file() and STATE.read_text().strip() == 'playful':
        return 'playful'
    return 'original'


def select(voice):
    folder = BANK / 'voices/playful' if voice == 'playful' else BANK
    durations = json.loads((folder / 'durations.json').read_text())
    lines = json.loads((BANK / 'lines.json').read_text())
    if voice == 'playful':
        owner_extras = json.loads((folder / 'owner-captions.json').read_text())
        for scene, phrases in owner_extras.items():
            lines[scene].extend(phrases)
        captions = json.loads((BANK / 'visitor-captions.json').read_text())
        lines.update({f'{scene}_loop': phrases for scene, phrases in captions.items()})
    for scene, phrases in lines.items():
        for index in range(len(phrases)):
            key = f'{scene}-{index}'
            with wave.open(str(folder / 'clips' / f'{key}.wav')) as wav:
                actual = wav.getnframes() / wav.getframerate()
            if actual <= 0 or abs(actual - durations[key]) > .01:
                raise ValueError(f'音频时长校验失败：{key}')
    STATE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=STATE.parent, delete=False) as output:
        output.write(voice + '\n')
    os.replace(output.name, STATE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('voice', nargs='?', choices=LABELS)
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    if args.status:
        print(LABELS[current()])
        return
    voice = args.voice
    if voice is None:
        choices = []
        for key, label in LABELS.items():
            choices.extend(['TRUE' if key == current() else 'FALSE', key, label])
        result = subprocess.run(['zenity', '--list', '--radiolist', '--title=鲸娘配音切换',
                                 '--text=下一句开始使用选中的声音', '--column=选择', '--column=代号',
                                 '--column=音色', '--hide-column=2', '--print-column=2', *choices],
                                text=True, stdout=subprocess.PIPE)
        if result.returncode:
            return
        voice = result.stdout.strip()
    if voice not in LABELS:
        raise SystemExit('音色无效')
    select(voice)
    print(LABELS[voice])


if __name__ == '__main__':
    main()
