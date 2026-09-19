from argparse import Namespace
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta
import io
import json
import unittest

from offline_boundary import temp
from trading_scanner.cli import main
from trading_scanner.core import calculate, DataError
from trading_scanner.dashboard import combine, synthetic_ota, FILTER_DEFAULTS, save_history, history_previous
from trading_scanner.demo import make_snapshot


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = make_snapshot()
        self.ota = synthetic_ota(self.snapshot)
        self.now = datetime.fromisoformat(self.ota['retrieved_at'])

    def test_join_preserves_scores_and_missing_unknown(self):
        result = combine(self.snapshot, self.ota, now=self.now)
        self.assertEqual(result['ranked'], calculate(self.snapshot)['ranked'])
        self.assertEqual(len(result['combined']), 60)
        absent = next(r for r in result['combined'] if r['symbol'] == 'S00')
        self.assertEqual(absent['ota_status'], 'not_returned_by_screener')
        self.assertIsNone(absent['totalOptionsVolume'])
        self.assertEqual(absent['review_status'], 'unknown')

    def test_stale_and_future_cannot_match_filters(self):
        for now in (self.now + timedelta(days=3), self.now - timedelta(days=1)):
            result = combine(self.snapshot, self.ota, now=now)
            self.assertFalse(any(r['review_status'] == 'matches_config_unverified' for r in result['combined']))

    def test_history_repeated_session_does_not_create_extra_day(self):
        directory = temp / 'dashboard-history'
        old = deepcopy(self.snapshot)
        old['sessions'] = old['sessions'][:-1]
        old['as_of'] = old['sessions'][-1]
        save_history(directory, calculate(old))
        previous = history_previous(directory, self.snapshot)
        result = combine(self.snapshot, self.ota, now=self.now, previous=previous)
        self.assertTrue(all(r['history_status'] == 'previous_session' for r in result['combined']))
        save_history(directory, result)
        save_history(directory, result)
        self.assertEqual(len(list(directory.glob('*.json'))), 2)
        self.assertEqual(history_previous(directory, self.snapshot), previous)

    def test_filters_preserve_missing_values_and_reject_invalid_config(self):
        config = {**FILTER_DEFAULTS, 'min_days_to_earnings': 60}
        result = combine(self.snapshot, self.ota, config, now=self.now)
        self.assertFalse(any(r['review_status'] == 'matches_config_unverified' for r in result['combined']))
        with self.assertRaises(DataError):
            combine(self.snapshot, self.ota, {**config, 'arbitrary': 1}, now=self.now)
        wrong = {**self.ota, 'source': 'ota'}
        with self.assertRaises(DataError):
            combine(self.snapshot, wrong, now=self.now)

    def test_demo_end_to_end(self):
        root = temp / 'dashboard-demo'
        root.mkdir()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['dashboard-demo'], root), 0)
        path = next(root.glob('artifacts/dashboards/synthetic/*/dashboard.html'))
        html = path.read_text()
        self.assertIn('SYNTHETIC DEMO', html)
        self.assertIn('Momentum + options research', html)
        self.assertTrue(path.with_name('combined.csv').exists())
        self.assertTrue(path.with_name('candidates.csv').exists())
        summary = json.loads(next(root.glob('artifacts/agent-review/*.json')).read_text())
        self.assertEqual(summary['counts']['ranked'], 60)
        self.assertNotIn('S00', json.dumps(summary))

    def test_untrusted_display_escaped(self):
        from trading_scanner.dashboard import write_dashboard
        self.snapshot['universe'][0]['company'] = '<script>bad()</script>'
        result = combine(self.snapshot, self.ota, now=self.now)
        directory = temp / 'dashboard-escaped'
        write_dashboard(result, directory)
        self.assertNotIn('<script>bad()', (directory / 'dashboard.html').read_text())

    def test_old_prices_with_new_ota_do_not_match(self):
        now = self.now + timedelta(days=7)
        ota = {**self.ota, 'retrieved_at': now.isoformat()}
        result = combine(self.snapshot, ota, now=now)
        self.assertEqual(result['price_status'], 'stale')
        self.assertFalse(any(r['review_status'] == 'matches_config_unverified' for r in result['combined']))

    def test_history_gap_and_corrupt_date(self):
        directory = temp / 'history-gap'
        old = deepcopy(self.snapshot)
        old['sessions'] = old['sessions'][:-2]
        old['as_of'] = old['sessions'][-1]
        save_history(directory, calculate(old))
        prior = history_previous(directory, self.snapshot)
        result = combine(self.snapshot, self.ota, now=self.now, previous=prior)
        self.assertTrue(all(r['history_status'] == 'history_gap' for r in result['combined']))
        path = next(directory.glob('*.json'))
        prior['as_of'] = '2000-01-01'
        path.write_text(json.dumps(prior))
        with self.assertRaisesRegex(DataError, 'HISTORY_INVALID'):
            history_previous(directory, self.snapshot)
