"""Read-only account limits and local token counters; no prompts or credentials cached."""
import asyncio
from contextlib import closing
from datetime import datetime
import json
from pathlib import Path
import shutil
import sqlite3
import threading
import time


def number(value):
    try:
        result = float(value)
        return max(0.0, result) if result < float('inf') else None
    except (TypeError, ValueError, OverflowError):
        return None


def normalize_limits(response, observed_at=None):
    limits = (response.get('rateLimitsByLimitId') or {}).get('codex') or response.get('rateLimits') or response
    windows = []
    for key in ('primary', 'secondary'):
        window = limits.get(key)
        if not isinstance(window, dict):
            continue
        used = number(window.get('usedPercent', window.get('used_percent')))
        minutes = number(window.get('windowDurationMins', window.get('window_minutes')))
        reset = number(window.get('resetsAt', window.get('resets_at')))
        if used is None or minutes is None:
            continue
        remaining = min(100.0, max(0.0, 100.0 - used))
        label = '周额度' if minutes >= 10080 else (f'{minutes / 60:g}小时额度' if minutes >= 60 else f'{minutes:g}分钟额度')
        windows.append({'remaining': remaining, 'minutes': minutes, 'reset': reset, 'label': label})
    credits = limits.get('credits') or {}
    result = {'quota_updated_at': observed_at or time.time(), 'quota_windows': windows,
              'credits': number(credits.get('balance')), 'credits_unlimited': credits.get('unlimited') is True}
    return result


async def read_account_limits(binary):
    process = await asyncio.create_subprocess_exec(str(binary), 'app-server', '--listen', 'stdio://',
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    async def send(message):
        process.stdin.write((json.dumps(message) + '\n').encode())
        await process.stdin.drain()
    async def response(request_id):
        while True:
            line = await asyncio.wait_for(process.stdout.readline(), 12)
            if not line:
                raise RuntimeError('Account reader exited')
            message = json.loads(line)
            if message.get('id') == request_id:
                if message.get('error'):
                    raise RuntimeError('Account limits unavailable')
                return message.get('result') or {}
    try:
        await send({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'mirabox-status', 'version': '1.0'}}})
        await response(1)
        await send({'method': 'initialized'})
        await send({'id': 2, 'method': 'account/rateLimits/read', 'params': None})
        return await response(2)
    finally:
        if process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
        try:
            await asyncio.wait_for(process.wait(), 3)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()


def local_usage(home):
    """Read token metadata only. Each provider's counter has its own session scope."""
    home = Path(home)
    result = {'codex_tokens': None, 'deepseek_tokens': None}
    try:
        database = home / '.codex/state_5.sqlite'
        with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True, timeout=.2)) as connection:
            rows = connection.execute('SELECT rollout_path,tokens_used FROM threads WHERE archived=0 ORDER BY updated_at_ms DESC LIMIT 16').fetchall()
        for path, tokens in rows:
            if Path(path).is_file():
                result['codex_tokens'] = number(tokens)
                with Path(path).open('rb') as stream:
                    stream.seek(max(0, Path(path).stat().st_size - 2 * 1024 * 1024))
                    lines = stream.read().splitlines()
                for line in reversed(lines):
                    if b'"token_count"' not in line:
                        continue
                    try:
                        item = json.loads(line)
                        payload = item.get('payload', {})
                        if item.get('type') != 'event_msg' or payload.get('type') != 'token_count':
                            continue
                        info = payload.get('info') or {}
                        count = number((info.get('total_token_usage') or {}).get('total_tokens'))
                        if count is not None:
                            result['codex_tokens'] = count
                        if payload.get('rate_limits'):
                            at = datetime.fromisoformat(item['timestamp'].replace('Z', '+00:00')).timestamp()
                            result.update(normalize_limits(payload['rate_limits'], at))
                        break
                    except (ValueError, TypeError, KeyError):
                        continue
                break
    except (OSError, sqlite3.Error):
        pass
    sessions = []
    for path in (home / '.dsh/storages/session_projcache/sessions').glob('*.json'):
        try:
            rows = json.loads(path.read_text())['record']['rows']
            totals = (rows.get('tokenUsage', {}).get('val') or {}).get('totals', {})
            parts = [number(totals.get(key)) for key in ('uncachedInputTokens', 'outputTokens', 'cacheReadTokens', 'cacheWriteTokens')]
            if any(value is None for value in parts):
                continue
            count = sum(parts)
            active = (rows.get('turnBoundary', {}).get('val') or {}).get('openTurnStartSeq') is not None
            sessions.append((active, count > 0, path.stat().st_mtime, count))
        except (OSError, ValueError, TypeError, KeyError):
            continue
    if sessions:
        result['deepseek_tokens'] = max(sessions)[3]
    return result


class UsageStatus:
    def __init__(self, home, state):
        self.home = Path(home)
        self.path = Path(state) / 'usage-status.json'
        self.value = {}
        try:
            self.value = json.loads(self.path.read_text())
        except (OSError, ValueError):
            pass
        self.worker = None
        self.next_local = 0
        self.next_remote = time.monotonic() + max(0, 300 - (time.time() - self.value.get('quota_updated_at', 0)))

    def sample(self):
        now = time.monotonic()
        if now >= self.next_local and (self.worker is None or not self.worker.is_alive()):
            self.next_local = now + 10
            self.worker = threading.Thread(target=self.refresh, daemon=True)
            self.worker.start()
        result = dict(self.value)
        windows = result.get('quota_windows') or []
        valid = [window for window in windows if not window.get('reset') or window['reset'] > time.time()]
        chosen = max(valid, key=lambda window: window['minutes']) if valid else {}
        result['quota_remaining'] = chosen.get('remaining')
        result['quota_reset_at'] = chosen.get('reset')
        result['quota_label'] = chosen.get('label', '周额度')
        result['quota_stale'] = time.time() - result.get('quota_updated_at', 0) > 900
        return result

    def refresh(self):
        current = dict(self.value)
        local = local_usage(self.home)
        if local.get('quota_updated_at', 0) < current.get('quota_updated_at', 0):
            for key in ('quota_windows', 'quota_updated_at', 'credits', 'credits_unlimited'):
                local.pop(key, None)
        current.update(local)
        self.value = current
        if time.monotonic() >= self.next_remote:
            self.next_remote = time.monotonic() + 300
            try:
                binary = shutil.which('codex') or self.home / '.local/bin/codex'
                remote = asyncio.run(asyncio.wait_for(read_account_limits(binary), 28))
                if remote.get('rateLimitsByLimitId') or remote.get('rateLimits'):
                    current.update(normalize_limits(remote))
            except (OSError, RuntimeError, ValueError, asyncio.TimeoutError):
                pass
        current['tokens_updated_at'] = time.time()
        self.value = current
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(current))
        temporary.replace(self.path)
