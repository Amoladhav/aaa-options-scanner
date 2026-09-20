"""Synthetic orchestration and credential-backend contract checks."""
import io
from argparse import Namespace
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch, Mock
import unittest
from offline_boundary import temp
from trading_scanner import token_store, workflow
from trading_scanner.core import DataError


class WorkflowTests(unittest.TestCase):
    def test_native_store_contract_and_sanitized_failure(self):
        store = Mock()
        store.get_password.return_value = 'synthetic-example'
        with patch.object(token_store, 'backend', return_value=store):
            self.assertEqual(token_store.load_token(), 'synthetic-example')
            token_store.operate('set', 'synthetic-example')
            token_store.operate('delete')
        store.set_password.assert_called_once_with(token_store.SERVICE, token_store.ENTRY, 'synthetic-example')
        store.delete_password.assert_called_once_with(token_store.SERVICE, token_store.ENTRY)
        stream = io.StringIO()
        def broken():
            print('private-provider-detail')
            raise RuntimeError('private-provider-detail')
        with patch.object(token_store, 'backend', side_effect=broken), redirect_stdout(stream), redirect_stderr(stream):
            with self.assertRaisesRegex(DataError, '^TOKEN_STORE_UNAVAILABLE$'):
                token_store.load_token()
        self.assertEqual(stream.getvalue(), '')

    def test_empty_invalid_token_and_no_silent_fallback(self):
        for value, code in [(None, 'TOKEN_STORE_EMPTY'), ('a\nb', 'OTA_TOKEN_INVALID')]:
            with patch.object(token_store, 'operate', return_value=value):
                with self.assertRaisesRegex(DataError, code):
                    token_store.load_token()

    def test_user_run_store_logs_never_contain_value(self):
        root = temp / 'store-command'
        output = io.StringIO()
        with patch('trading_scanner.ota_fetch.prompt_token', return_value='synthetic-example'), patch.object(token_store, 'operate') as operation, redirect_stdout(output):
            self.assertEqual(token_store.run_store(root, 'set'), 0)
        operation.assert_called_once_with('set', 'synthetic-example')
        for path in root.glob('artifacts/logs/*'):
            self.assertNotIn('synthetic-example', path.read_text())
        self.assertNotIn('synthetic-example', output.getvalue())

    def test_daily_uses_only_new_stage_outputs(self):
        root = temp / 'daily-success'
        old = root / 'artifacts/ota/old/results.json'
        old.parent.mkdir(parents=True); old.write_text('{}')
        price = root / 'artifacts/runs/public/new/snapshot.json'
        ota = root / 'artifacts/ota/new/results.json'
        def refresh(*args):
            price.parent.mkdir(parents=True); price.write_text('{}'); return 0
        def fetch(*args, **kwargs):
            ota.parent.mkdir(parents=True); ota.write_text('{}'); return 0
        args = Namespace(page_size=600, max_pages=50, use_stored_token=False, filters=None)
        with patch('trading_scanner.scan_service.run_scan', side_effect=refresh), patch('trading_scanner.ota_fetch.run_fetch', side_effect=fetch), patch.object(workflow, 'run_dashboard', return_value=0) as report:
            self.assertEqual(workflow.run_daily(root, args), 0)
        actual = report.call_args.args[1]
        self.assertEqual(actual.snapshot, price)
        self.assertEqual(actual.ota, ota)

    def test_daily_failed_fetch_never_uses_old_output(self):
        args = Namespace(page_size=600, max_pages=50, use_stored_token=False, filters=None)
        with patch('trading_scanner.scan_service.run_scan', return_value=0), patch('trading_scanner.ota_fetch.run_fetch', return_value=1), patch.object(workflow, 'run_dashboard') as report:
            self.assertEqual(workflow.run_daily(temp / 'daily-failed', args), 1)
        report.assert_not_called()

    def test_tradier_credentials_are_separated_by_profile(self):
        store = Mock()
        store.get_password.return_value = 'synthetic-example'
        with patch.object(token_store, 'backend', return_value=store):
            token_store.load_token(provider='tradier', profile='sandbox')
            token_store.load_token(provider='tradier', profile='production')
        self.assertEqual([call.args[0] for call in store.get_password.call_args_list],
                         ['aaa-options-scanner.tradier.sandbox', 'aaa-options-scanner.tradier.production'])
        with self.assertRaisesRegex(DataError, 'TOKEN_STORE_UNAVAILABLE'):
            token_store.operate('get', provider='tradier')

    def test_provider_specific_validation_and_paste_padding(self):
        self.assertEqual(token_store.valid_token('  synthetic-example  ', provider='tradier'), 'synthetic-example')
        for value in ('', 'a b', 'a\nb'):
            with self.assertRaisesRegex(DataError, '^TRADIER_TOKEN_INVALID$'):
                token_store.valid_token(value, provider='tradier')
        with self.assertRaisesRegex(DataError, '^OTA_TOKEN_INVALID$'):
            token_store.valid_token('')
