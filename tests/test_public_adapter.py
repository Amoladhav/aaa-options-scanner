"""Offline integration of the download orchestration with synthetic transports."""
import offline_boundary  # Fail closed if collected without the guarded runner.
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import urllib.request

from trading_scanner.core import calculate
from trading_scanner.demo import make_snapshot
from trading_scanner.public_data import fetch_snapshot


class PublicAdapterTests(unittest.TestCase):
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
                empty = False
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
        with patch.dict('sys.modules', {'exchange_calendars':fake_calendars, 'yfinance':fake_yf}), patch.object(urllib.request, 'urlopen', return_value=Response()):
            snapshot = fetch_snapshot(Path(__file__).resolve().parents[1]/'config/etfs.csv', now)
        self.assertEqual(len(snapshot['universe']), 511)
        self.assertEqual(len(calls), 13)
        self.assertTrue(all(len(symbols) <= 40 for symbols, _ in calls))
        self.assertTrue(all(k['auto_adjust'] is True and k['threads'] is False and k['repair'] is False for _, k in calls))
        self.assertEqual(snapshot['as_of'], days[-1])
        self.assertNotIn('2030-01-02', snapshot['prices']['SPY'])
        self.assertEqual(len(calculate(snapshot)['ranked']), 511)

    def test_safe_report_cannot_include_exception_text(self):
        from trading_scanner.cli import review_summary
        report = review_summary('a'*32, 'public', False, 0, 0, 'synthetic-secret-response')
        self.assertEqual(report['error_code'], 'SCAN_FAILED')
