import json
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from usage_status import normalize_limits, local_usage, UsageStatus


class UsageTests(unittest.TestCase):
    def test_zero_credit_and_exhausted_quota_are_real_values(self):
        value = normalize_limits({'primary': {'used_percent': 100, 'window_minutes': 10080, 'resets_at': time.time() + 100},
                                  'credits': {'balance': '0', 'unlimited': False}})
        self.assertEqual(value['quota_windows'][0]['remaining'], 0)
        self.assertEqual(value['credits'], 0)
        unknown = normalize_limits({})
        self.assertEqual(unknown['quota_windows'], [])
        self.assertIsNone(unknown['credits'])

    def test_expired_window_is_unknown_until_refreshed(self):
        with tempfile.TemporaryDirectory() as d:
            usage = UsageStatus(Path(d), Path(d))
            usage.next_local = time.monotonic() + 10
            usage.value = normalize_limits({'primary': {'usedPercent': 91, 'windowDurationMins': 10080, 'resetsAt': time.time() - 1}})
            self.assertIsNone(usage.sample()['quota_remaining'])

    def test_local_counters_keep_session_scope_and_include_cache_once(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            (home / '.codex').mkdir()
            log = home / '.codex/rollout.jsonl'
            event = {'type': 'event_msg', 'timestamp': '2026-11-17T07:00:00Z', 'payload': {
                'type': 'token_count', 'info': {'total_token_usage': {'total_tokens': 95, 'cached_input_tokens': 80}},
                'rate_limits': {'primary': {'used_percent': 25, 'window_minutes': 300}}}}
            log.write_text(json.dumps(event) + '\n')
            with closing(sqlite3.connect(home / '.codex/state_5.sqlite')) as connection:
                connection.execute('CREATE TABLE threads (rollout_path TEXT,tokens_used INTEGER,archived INTEGER,updated_at_ms INTEGER)')
                connection.execute('INSERT INTO threads VALUES (?,?,0,100)', (str(log), 80))
                connection.commit()
            sessions = home / '.dsh/storages/session_projcache/sessions'
            sessions.mkdir(parents=True)
            rows = {'tokenUsage': {'val': {'totals': {'uncachedInputTokens': 41, 'outputTokens': 12, 'cacheReadTokens': 100, 'cacheWriteTokens': 5}}}}
            (sessions / 'used.json').write_text(json.dumps({'record': {'rows': rows}}))
            zero_rows = {'tokenUsage': {'val': {'totals': dict.fromkeys(rows['tokenUsage']['val']['totals'], 0)}}}
            (sessions / 'empty.json').write_text(json.dumps({'record': {'rows': zero_rows}}))
            value = local_usage(home)
            self.assertEqual(value['codex_tokens'], 95)
            self.assertEqual(value['deepseek_tokens'], 158)
            self.assertEqual(value['quota_windows'][0]['remaining'], 75)


if __name__ == '__main__':
    unittest.main()
