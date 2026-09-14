from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

from offline_boundary import temp
from trading_scanner.cli import main, review_summary
from trading_scanner.core import calculate, DataError
from trading_scanner.demo import make_snapshot
from trading_scanner.public_data import load_etfs, parse_constituents, series_prices
from trading_scanner.report import csv_cell, write_reports


class OfflineIntegrationTests(unittest.TestCase):
    def directory(self, name):
        p = temp / name
        p.mkdir(exist_ok=False)
        return p

    def test_real_network_subprocess_and_secret_reads_denied(self):
        for operation in (lambda: socket.socket(),
                          lambda: subprocess.run([sys.executable, "-c", "pass"]),
                          lambda: Path('/outside-allowlist/synthetic-secret').read_text(),
                          lambda: os.getenv('SYNTHETIC_CREDENTIAL'),
                          lambda: os.environ['SYNTHETIC_CREDENTIAL']):
            with self.assertRaises(PermissionError):
                operation()

    def test_demo_command_end_to_end(self):
        root = self.directory('demo')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['demo'], root), 0)
        reports = list(root.glob('artifacts/runs/synthetic/*/report.html'))
        self.assertEqual(len(reports), 1)
        self.assertIn('SYNTHETIC DEMO', reports[0].read_text())
        result = json.loads(reports[0].with_name('results.json').read_text())
        self.assertEqual(len(result['ranked']), 60)
        self.assertEqual(len(reports[0].with_name('rankings.csv').read_text().splitlines()), 61)

    def test_cached_replay_is_deterministic_and_separate(self):
        root = self.directory('replay')
        path = root / 'synthetic.json'
        snapshot = make_snapshot()
        path.write_text(json.dumps(snapshot), encoding='utf-8')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['cached', '--snapshot', str(path)], root), 0)
        result = json.loads(next(root.glob('artifacts/replay/synthetic/*/results.json')).read_text())
        self.assertEqual(result['ranked'], calculate(snapshot)['ranked'])
        self.assertFalse((root / 'artifacts/runs/public').exists())

    def test_malformed_cached_profile_fails_safely(self):
        root = self.directory('malformed')
        path = root / 'invalid.json'
        path.write_text(json.dumps({'profile':['unexpected']}), encoding='utf-8')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['cached', '--snapshot', str(path)], root), 1)
        report = json.loads(next(root.glob('artifacts/agent-review/*.json')).read_text())
        self.assertEqual(report['error_code'], 'INVALID_SNAPSHOT')

    def test_public_failure_never_falls_back_or_leaks(self):
        root = self.directory('failure')
        marker = 'synthetic-private-response-marker'
        output = io.StringIO()
        with patch('trading_scanner.public_data.fetch_snapshot', side_effect=RuntimeError(marker)), redirect_stdout(output):
            self.assertEqual(main(['refresh', '--profile', 'public'], root), 1)
        self.assertNotIn(marker, output.getvalue())
        report = next(root.glob('artifacts/agent-review/*.json')).read_text()
        self.assertNotIn(marker, report)
        self.assertFalse((root / 'artifacts/runs').exists())
        self.assertEqual(json.loads(report)['profile'], 'public')

    def test_public_command_with_synthetic_transport(self):
        root = self.directory('public-fake')
        snapshot = make_snapshot()
        snapshot['profile'] = 'public'
        with patch('trading_scanner.public_data.fetch_snapshot', return_value=snapshot), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['refresh', '--profile', 'public'], root), 0)
        summary = json.loads(next(root.glob('artifacts/agent-review/*.json')).read_text())
        self.assertEqual(set(summary), {'schema_version','run_id','code_revision','profile','checks','counts','error_code'})
        self.assertNotIn('S00', json.dumps(summary))
        self.assertEqual(summary['counts'], {'ranked':60, 'excluded':0})

    def test_auth_cannot_select_mode_and_report_metadata_validated(self):
        with self.assertRaises(DataError):
            review_summary('malicious-metadata', 'public', True, 1, 1)
        with self.assertRaises(DataError):
            review_summary('a'*32, 'production', True, 1, 1)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(['refresh'], self.directory('no-profile'))

    def test_html_and_csv_injection_are_escaped(self):
        root = self.directory('escaping')
        result = calculate(make_snapshot())
        result['ranked'][0]['company'] = '<script>alert(1)</script>'
        write_reports(result, root)
        html = (root/'report.html').read_text()
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertEqual(csv_cell('=1+1'), "'=1+1")
        self.assertEqual(csv_cell(-.5), -.5)

    def test_constituents_table_and_share_class_mapping(self):
        html = '<table id="constituents"><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th></tr><tr><td>BRK.B</td><td>Example &amp; Co</td><td>Financials</td></tr></table><table><tr><td>IGNORE</td></tr></table>'
        rows = parse_constituents(html, minimum=1)
        self.assertEqual(rows[0]['symbol'], 'BRK-B')
        self.assertEqual(rows[0]['company'], 'Example & Co')
        with self.assertRaises(DataError):
            parse_constituents(html)
        with self.assertRaises(DataError):
            parse_constituents('<html>blocked</html>')

    def test_etf_universe_has_11_sectors_and_50_additions(self):
        path = Path(__file__).resolve().parents[1] / 'config/etfs.csv'
        rows = load_etfs(path)
        self.assertEqual(len(rows), 61)
        self.assertEqual(sum(r['sector_etf'] for r in rows), 11)
        self.assertIn('SPY', [r['symbol'] for r in rows])

    def test_price_conversion_drops_invalid_and_future(self):
        series = {datetime(2025,1,2):100, datetime(2025,1,3):float('nan'), datetime(2030,1,2):900}
        self.assertEqual(series_prices(series, {'2025-01-02','2025-01-03'}), {'2025-01-02':100})
