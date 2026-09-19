from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
import unittest

from offline_boundary import temp
from trading_scanner.cli import main
from trading_scanner.core import calculate, DataError
from trading_scanner.demo import make_snapshot
from trading_scanner.options_data import enrich, synthetic_options, validate_options, METRICS


class OptionsTests(unittest.TestCase):
    def setUp(self):
        self.result = calculate(make_snapshot())
        self.payload = synthetic_options(self.result)

    def test_join_preserves_scores_and_unknowns(self):
        original = deepcopy(self.result)
        result = enrich(self.result, self.payload)
        self.assertEqual(result['ranked'], original['ranked'])
        self.assertEqual(self.result, original)
        rows = result['options']['rows']
        self.assertEqual(len(rows), 60)
        self.assertEqual(rows[0]['options_status'], 'missing')
        self.assertTrue(all(rows[0][k] is None for k in METRICS))
        self.assertEqual(rows[4]['options_status'], 'partial')
        self.assertIsNone(rows[4]['option_volume'])
        self.assertNotEqual(rows[1]['iv_rank'], rows[1]['iv_percentile'])

    def test_stale_and_future_metrics_withheld(self):
        for session, expected in [('2025-07-29', 'stale'), ('2025-07-31', 'future')]:
            self.payload['rows'][0]['as_of'] = session
            row = enrich(self.result, self.payload)['options']['rows'][1]
            self.assertEqual(row['options_status'], expected)
            self.assertTrue(all(row[k] is None for k in METRICS))

    def test_invalid_metrics_and_schema(self):
        for key, value in [('iv_rank', True), ('iv_rank', float('nan')), ('iv_percentile', 101),
                           ('option_volume', -1), ('open_interest', 1.5), ('as_of', '2025-08-02'),
                           ('as_of', '20250730'), ('symbol', None), ('unexpected', 'discard-me')]:
            payload = deepcopy(self.payload)
            payload['rows'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaisesRegex(DataError, 'INVALID_OPTIONS_INPUT'):
                validate_options(payload, 'synthetic')

    def test_duplicates_and_profile_mixing_rejected(self):
        self.payload['rows'].append(deepcopy(self.payload['rows'][0]))
        with self.assertRaises(DataError):
            validate_options(self.payload, 'synthetic')
        with self.assertRaises(DataError):
            validate_options(synthetic_options(self.result), 'public')

    def test_zero_is_valid_and_empty_coverage_is_missing(self):
        for key in METRICS:
            self.payload['rows'][0][key] = 0
        row = enrich(self.result, self.payload)['options']['rows'][1]
        self.assertEqual(row['options_status'], 'aligned')
        self.assertEqual(row['option_volume'], 0)
        self.payload['rows'] = []
        self.assertTrue(all(r['options_status'] == 'missing' for r in enrich(self.result, self.payload)['options']['rows']))

    def test_demo_and_cached_replay_with_progress(self):
        root = temp / 'options-demo'
        root.mkdir()
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(['demo', '--with-options'], root), 0)
        path = next(root.glob('artifacts/runs/synthetic/*/snapshot.json'))
        report = path.with_name('report.html').read_text()
        self.assertIn('SYNTHETIC OPTIONS', report)
        self.assertIn('Unknown', report)
        self.assertTrue(path.with_name('options.csv').exists())
        self.assertIn('Validating and joining offline options metrics', stdout.getvalue())
        original = json.loads(path.with_name('results.json').read_text())
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['cached', '--snapshot', str(path)], root), 0)
        replay = json.loads(next(root.glob('artifacts/replay/synthetic/*/results.json')).read_text())
        self.assertEqual(original['options'], replay['options'])
        self.assertEqual(original['ranked'], replay['ranked'])

    def test_bad_input_fails_with_safe_code(self):
        root = temp / 'options-invalid'
        root.mkdir()
        snapshot = root / 'snapshot.json'
        snapshot.write_text(json.dumps(make_snapshot()))
        source = root / 'options.json'
        source.write_text('{"unexpected":"private-synthetic-marker"}')
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            self.assertEqual(main(['cached', '--snapshot', str(snapshot), '--options-file', str(source)], root), 1)
        self.assertNotIn('private-synthetic-marker', stdout.getvalue())
        summary = json.loads(next(root.glob('artifacts/agent-review/*.json')).read_text())
        self.assertEqual(summary['error_code'], 'INVALID_OPTIONS_INPUT')
        self.assertFalse(list(root.glob('artifacts/replay/*/*/report.html')))

    def test_explicit_file_and_public_label(self):
        root = temp / 'options-file'
        root.mkdir()
        snapshot = make_snapshot()
        snapshot['profile'] = 'public'
        path = root / 'snapshot.json'
        path.write_text(json.dumps(snapshot))
        payload = deepcopy(self.payload)
        payload['source'] = 'user_supplied'
        source = root / 'options.json'
        source.write_text(json.dumps(payload))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['cached', '--snapshot', str(path), '--options-file', str(source)], root), 0)
        report = next(root.glob('artifacts/replay/public/*/report.html'))
        self.assertIn('USER-SUPPLIED OPTIONS', report.read_text())
        stored = json.loads(report.with_name('snapshot.json').read_text())
        self.assertEqual(stored['options_input'], payload)
        for log in root.glob('artifacts/logs/*'):
            self.assertNotIn('iv_rank', log.read_text())
