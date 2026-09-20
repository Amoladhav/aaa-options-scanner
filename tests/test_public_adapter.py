"""Offline integration of the download orchestration with synthetic transports."""
from throttle_fixtures import virtual_throttle_time
import offline_boundary  # Fail closed if collected without the guarded runner.
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request
import io
import json

from offline_boundary import temp
from trading_scanner.progress import RunProgress

from trading_scanner.core import calculate
from trading_scanner.demo import make_snapshot
from trading_scanner.public_data import fetch_snapshot


class PublicAdapterTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(virtual_throttle_time())

    def test_download_batches_adjustment_cutoff_and_universe_join(self):
        fixture = make_snapshot()
        days = fixture['sessions']
        html = '<table id="constituents"><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th></tr>'
        html += ''.join(f'<tr><td>S{i:03}</td><td>Synthetic {i}</td><td>Example</td></tr>' for i in range(450))
        html += '</table>'

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return html.encode('utf-8')

        class Schedule:
            def iterrows(self):
                return [(datetime.fromisoformat(d), {'close': datetime.fromisoformat(d+'T20:00:00+00:00')}) for d in days]

        calls = []
        def download(symbols, **kwargs):
            calls.append((symbols, kwargs))
            class Frame:
                # Simulate one empty response: attempted batches still advance,
                # but missing symbols must not count as received or ranked.
                empty = len(calls) == 2
                columns = SimpleNamespace(get_level_values=lambda level: symbols)
                def __getitem__(self, symbol):
                    # Provider includes a future row; adapter must discard it.
                    data = {datetime.fromisoformat(d): 100+j*.1 for j,d in enumerate(days)}
                    data[datetime(2030,1,2)] = 99999
                    return {'Close': data}
            return Frame()

        fake_calendars = SimpleNamespace(get_calendar=lambda *a, **kw: SimpleNamespace(schedule=Schedule()))
        fake_yf = SimpleNamespace(download=download)
        now = datetime.fromisoformat(days[-1]+'T22:00:00+00:00')
        tracker = RunProgress(temp/'adapter-progress', 'c'*32, 'refresh', 'public', 'd'*64, stream=io.StringIO())
        try:
            with patch.dict('sys.modules', {'exchange_calendars':fake_calendars, 'yfinance':fake_yf}), patch('trading_scanner.public_transport.read_constituents', return_value=html.encode()), patch('trading_scanner.public_transport.make_yahoo_session'):
                snapshot = fetch_snapshot(Path(__file__).resolve().parents[1]/'config/etfs.csv', now, progress=tracker)
        finally:
            tracker.close()
        self.assertEqual(len(snapshot['universe']), 511)
        self.assertEqual(len(calls), 13)
        self.assertTrue(all(len(symbols) <= 40 for symbols, _ in calls))
        self.assertTrue(all(k['auto_adjust'] is True and k['threads'] is False and k['repair'] is False for _, k in calls))
        self.assertEqual(snapshot['as_of'], days[-1])
        self.assertNotIn('2030-01-02', snapshot['prices']['SPY'])
        self.assertEqual(len(calculate(snapshot)['ranked']), 471)
        events = [json.loads(line) for line in tracker.path.read_text().splitlines()]
        self.assertEqual([r['stage'] for r in events if r['event'] == 'stage_started'],
                         ['dependencies', 'constituents', 'calendar', 'prices'])
        batches = [r for r in events if r['event'] == 'stage_progress' and r['stage'] == 'prices' and r['step'] == 'prices']
        self.assertEqual([r['completed'] for r in batches[:13]], list(range(1,14)))
        self.assertEqual(batches[1]['counts']['symbols_received'], batches[0]['counts']['symbols_received'])
        self.assertEqual(batches[12]['counts'], {'symbols_requested':511, 'symbols_received':471})

    def test_safe_report_cannot_include_exception_text(self):
        from trading_scanner.cli import review_summary
        report = review_summary('a'*32, 'public', False, 0, 0, 'synthetic-secret-response')
        self.assertEqual(report['error_code'], 'SCAN_FAILED')
