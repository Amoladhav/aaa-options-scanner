"""Synthetic-only progress, lifecycle, file failure, and log privacy checks."""
from contextlib import redirect_stdout
from datetime import datetime
import io
import json
import logging
from pathlib import Path
import unittest
from unittest.mock import patch

from offline_boundary import temp
from trading_scanner.cli import main
from trading_scanner.demo import make_snapshot
from trading_scanner.progress import RunProgress


def read_log(root):
    return [json.loads(line) for line in next(root.glob('artifacts/logs/*.jsonl')).read_text().splitlines()]


class ProgressTests(unittest.TestCase):
    def root(self):
        root = temp / self._testMethodName
        root.mkdir()
        return root

    def test_demo_logs_match_stdout_and_final_summary(self):
        root, output = self.root(), io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['demo'], root), 0)
        records = read_log(root)
        self.assertEqual(records[0]['event'], 'run_started')
        self.assertEqual(records[-1]['event'], 'run_finished')
        self.assertEqual(records[-1]['percent'], 100)
        self.assertEqual(records[-1]['counts'], {'ranked': 60, 'excluded': 0})
        self.assertEqual([r['sequence'] for r in records], list(range(1, len(records)+1)))
        expected = {'schema_version', 'timestamp', 'timezone', 'timestamp_utc', 'sequence', 'level', 'run_id',
                    'code_revision', 'command', 'profile', 'event', 'stage', 'step', 'message',
                    'completed', 'total', 'percent', 'elapsed_seconds',
                    'stage_elapsed_seconds', 'counts', 'error_code'}
        summary = json.loads(next(root.glob('artifacts/agent-review/*.json')).read_text())
        for r in records:
            self.assertEqual(set(r), expected)
            self.assertIsNotNone(datetime.fromisoformat(r['timestamp_utc']).utcoffset())
            self.assertEqual(r['run_id'], summary['run_id'])
            self.assertEqual(r['code_revision'], summary['code_revision'])
            self.assertIn(r['message'], output.getvalue())
        self.assertEqual([r['stage'] for r in records if r['event'] == 'stage_started'],
                         ['synthetic_data', 'ranking', 'reports', 'summary'])
        self.assertIn('[####################] 100%', output.getvalue())
        self.assertIn('Currently running: Calculating cross-sectional momentum', output.getvalue())
        self.assertNotIn('\r', output.getvalue())

    def test_provider_noise_suppressed_but_progress_visible_and_flushed(self):
        root, output = self.root(), io.StringIO()
        marker = 'synthetic-private-provider-body'
        def fake_fetch(path, *, progress):
            progress.start('prices', total=2)
            print(marker)
            logging.error(marker)
            # Records and stdout must be available before the operation returns.
            self.assertIn('Currently running: Downloading adjusted daily prices', output.getvalue())
            self.assertEqual(read_log(root)[-1]['event'], 'stage_started')
            progress.advance(1, counts={'symbols_requested': 40, 'symbols_received': 39})
            progress.advance(2, counts={'symbols_requested': 60, 'symbols_received': 59})
            progress.finish()
            data = make_snapshot()
            data['profile'] = 'public'
            return data
        old_disable = logging.root.manager.disable
        with patch('trading_scanner.public_data.fetch_snapshot', side_effect=fake_fetch), redirect_stdout(output):
            self.assertEqual(main(['refresh', '--profile', 'public'], root), 0)
        records = read_log(root)
        self.assertEqual([r['percent'] for r in records if r['event'] == 'stage_progress'], [50, 100])
        self.assertNotIn(marker, output.getvalue())
        self.assertNotIn(marker, json.dumps(records))
        self.assertEqual(logging.root.manager.disable, old_disable)

    def test_failure_retains_stage_and_incomplete_progress(self):
        root, output = self.root(), io.StringIO()
        marker = 'synthetic-exception-with-private-content'
        def fail(path, *, progress):
            progress.start('prices', total=4)
            progress.advance(1)
            raise RuntimeError(marker)
        with patch('trading_scanner.public_data.fetch_snapshot', side_effect=fail), redirect_stdout(output):
            self.assertEqual(main(['refresh', '--profile', 'public'], root), 1)
        records = read_log(root)
        self.assertEqual(records[-1]['event'], 'run_failed')
        self.assertEqual(records[-1]['stage'], 'prices')
        self.assertEqual(records[-1]['percent'], 25)
        self.assertEqual(records[-1]['error_code'], 'SCAN_FAILED')
        self.assertNotIn('run_finished', [r['event'] for r in records])
        self.assertNotIn(marker, json.dumps(records) + output.getvalue())

    def test_interrupt_logs_cancellation_without_success(self):
        root, output = self.root(), io.StringIO()
        with patch('trading_scanner.cli.calculate', side_effect=KeyboardInterrupt), redirect_stdout(output):
            self.assertEqual(main(['demo'], root), 130)
        records = read_log(root)
        self.assertEqual(records[-1]['event'], 'run_cancelled')
        self.assertEqual(records[-1]['stage'], 'ranking')
        self.assertEqual(records[-1]['completed'], 0)
        summary = json.loads(next(root.glob('artifacts/agent-review/*.json')).read_text())
        self.assertEqual(summary['error_code'], 'RUN_CANCELLED')

    def test_cached_profile_resolved_after_read(self):
        root, output = self.root(), io.StringIO()
        path = root / 'synthetic.json'
        path.write_text(json.dumps(make_snapshot()), encoding='utf-8')
        with redirect_stdout(output):
            self.assertEqual(main(['cached', '--snapshot', str(path)], root), 0)
        records = read_log(root)
        self.assertEqual(records[0]['profile'], 'unknown')
        self.assertEqual(records[-1]['profile'], 'synthetic')
        self.assertIn('profile_resolved', [r['event'] for r in records])

    def test_exclusions_warning_uses_counts_only(self):
        root = self.root()
        snapshot = make_snapshot()
        del snapshot['prices']['S00']
        with patch('trading_scanner.cli.make_snapshot', return_value=snapshot), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['demo'], root), 0)
        records = read_log(root)
        warning = next(r for r in records if r['event'] == 'symbols_excluded')
        self.assertEqual(warning['level'], 'WARNING')
        self.assertEqual(warning['counts'], {'excluded': 1})
        self.assertNotIn('S00', json.dumps(records))

    def test_log_creation_failure_is_sanitized_and_does_not_run_scan(self):
        root, output = self.root(), io.StringIO()
        with patch('trading_scanner.cli.RunProgress', side_effect=OSError('synthetic-private-path')), patch('trading_scanner.cli.make_snapshot') as generate, redirect_stdout(output):
            self.assertEqual(main(['demo'], root), 1)
            generate.assert_not_called()
        self.assertNotIn('synthetic-private-path', output.getvalue())
        summary = json.loads(next(root.glob('artifacts/agent-review/*.json')).read_text())
        self.assertEqual(summary['error_code'], 'LOG_UNAVAILABLE')

    def test_log_write_failure_never_reports_success(self):
        root, output = self.root(), io.StringIO()
        with patch.object(RunProgress, '_emit', side_effect=OSError('synthetic-disk-error')), redirect_stdout(output):
            self.assertEqual(main(['demo'], root), 1)
        self.assertNotIn('synthetic-disk-error', output.getvalue())
        self.assertNotIn('Run completed', output.getvalue())

    def test_public_metadata_rejected_and_existing_logs_preserved(self):
        root = self.root()
        tracker = RunProgress(root, 'a'*32, 'demo', 'synthetic', 'b'*64, stream=io.StringIO())
        try:
            tracker.begin()
            with self.assertRaises(ValueError):
                tracker.start('synthetic-sensitive-stage')
            tracker.start('prices', total=3)
            with self.assertRaises(ValueError):
                tracker.advance(4)
            with self.assertRaises(ValueError):
                tracker.advance(1, counts={'symbol': 'S00'})
            tracker.end('synthetic-sensitive-error')
        finally:
            tracker.close()
        text = tracker.path.read_text()
        self.assertNotIn('synthetic-sensitive', text)
        with self.assertRaises(FileExistsError):
            RunProgress(root, 'a'*32, 'demo', 'synthetic', 'b'*64, stream=io.StringIO())
        self.assertEqual(tracker.path.read_text(), text)

    def test_terminal_refresh_reuses_line_and_clears_before_prompt(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        root, output = self.root(), Terminal()
        tracker = RunProgress(root, 'c'*32, 'tradier-fetch', 'production', 'd'*64, stream=output)
        try:
            tracker.begin()
            tracker.start('tradier_batch', total=10)
            before = output.getvalue().count('\n')
            tracker.advance(1, counts={'symbols_received': 1}, detail='tradier_chain')
            tracker.advance(2, counts={'symbols_received': 2}, detail='tradier_quote')
            self.assertEqual(output.getvalue().count('\n'), before)
            self.assertIn('\r', output.getvalue())
            self.assertIn('Fetching underlying quote', output.getvalue())
            tracker.start('tradier_auth')
            self.assertEqual(tracker.line_width, 0)
            self.assertTrue(output.getvalue().endswith('\n'))
            tracker.end(counts={'symbols_received': 2})
            self.assertIn('Summary: status=completed', output.getvalue())
            self.assertIn('symbols_received=2', output.getvalue())
            self.assertIn(str(tracker.error_path), output.getvalue())
        finally:
            tracker.close()
        records = [json.loads(line) for line in tracker.path.read_text().splitlines()]
        self.assertEqual(sum(r['event'] == 'stage_progress' for r in records), 2)
        self.assertTrue(all('\r' not in json.dumps(r) for r in records))
        self.assertEqual(tracker.error_path.read_text(), '')

    def test_error_file_and_partial_summary_preserve_safe_counts(self):
        root, output = self.root(), io.StringIO()
        tracker = RunProgress(root, 'e'*32, 'tradier-fetch', 'production', 'f'*64, stream=output)
        try:
            tracker.begin()
            tracker.start('tradier_batch', total=5)
            tracker.advance(2, counts={'master_symbols': 5, 'symbols_received': 1, 'requests': 6})
            tracker.error('TRADIER_SCHEMA_INVALID', counts={'symbols_failed': 1})
            tracker.error('synthetic-private-error')
            tracker.end('TRADIER_BATCH_PARTIAL')
        finally:
            tracker.close()
        errors = [json.loads(line) for line in tracker.error_path.read_text().splitlines()]
        self.assertEqual([r['error_code'] for r in errors], ['TRADIER_SCHEMA_INVALID', 'SCAN_FAILED', 'TRADIER_BATCH_PARTIAL'])
        self.assertNotIn('synthetic-private-error', tracker.error_path.read_text())
        self.assertIn('Summary: status=partial', output.getvalue())
        self.assertIn('symbols_failed=1', output.getvalue())
        self.assertIn('requests=6', output.getvalue())
        self.assertNotIn('\r', output.getvalue())

    def test_local_timestamp_keeps_offset_and_utc_in_structured_log(self):
        from datetime import timezone, timedelta
        root = self.root()
        class LocalDate(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 9, 19, 20, 0, tzinfo=timezone.utc)
            def astimezone(self, tz=None):
                return super().astimezone(tz or timezone(timedelta(hours=5, minutes=30), 'TestLocal'))
        with patch('trading_scanner.progress.datetime', LocalDate):
            tracker = RunProgress(root, '1'*32, 'demo', 'synthetic', '2'*64, stream=io.StringIO())
            try:
                tracker.begin()
            finally:
                tracker.close()
        record = json.loads(tracker.path.read_text().splitlines()[0])
        self.assertEqual(record['timestamp'], '2026-09-20T01:30:00+05:30')
        self.assertEqual(record['timestamp_utc'], '2026-09-19T20:00:00+00:00')
        self.assertEqual(record['timezone'], 'TestLocal')

    def test_narrow_terminal_keeps_step_without_wrapping(self):
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        tracker = RunProgress(self.root(), '3'*32, 'tradier-fetch', 'production', '4'*64, stream=Terminal())
        try:
            tracker.columns = 40
            tracker.start('tradier_batch', total=500)
            tracker.advance(17, detail='tradier_chain')
            self.assertLess(tracker.line_width, 40)
            self.assertIn('tradier chain', tracker.stream.getvalue().split('\r')[-1])
        finally:
            tracker.close()
