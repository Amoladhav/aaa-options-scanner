"""Synthetic-only credential contract and CLI regression coverage."""
import getpass
import importlib
import io
import json
import unittest
import warnings
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import Mock, patch
from offline_boundary import temp
from trading_scanner import credentials
from trading_scanner.cli import main
from trading_scanner.core import DataError


class CredentialTests(unittest.TestCase):
    def test_import_never_reads_environment(self):
        # The test runner denies every real environment read before collection.
        importlib.reload(credentials)

    def test_profile_reads_only_one_key(self):
        for (provider, profile), variable in credentials.VARIABLES.items():
            env = Mock()
            env.get.return_value = 'synthetic-example'
            self.assertEqual(credentials.resolve(provider, profile, source='env', environment=env), 'synthetic-example')
            env.get.assert_called_once_with(variable)
        env = Mock()
        with self.assertRaisesRegex(DataError, '^CREDENTIAL_PROFILE_INVALID$'):
            credentials.resolve('tradier', 'ota', source='env', environment=env)
        env.get.assert_not_called()

    def test_auto_precedence_and_absence_only_fallback(self):
        prompt, store = Mock(return_value='synthetic-example'), Mock()
        key = credentials.VARIABLES['ota', 'ota']
        credentials.resolve('ota', 'ota', source='auto', environment={key:'synthetic-env'}, prompt=prompt, store=store)
        prompt.assert_not_called(); store.assert_not_called()
        self.assertEqual(credentials.resolve('ota', 'ota', source='auto', environment={}, allow_prompt=True, prompt=prompt), 'synthetic-example')
        for value in ('', ' ', 'has space', 'has\nnewline', ' padded ', 'é', 42, 'a'*8193):
            with self.assertRaisesRegex(DataError, '^CREDENTIAL_INVALID$'):
                credentials.resolve('ota', 'ota', source='auto', environment={key:value}, allow_prompt=True, prompt=prompt)
        self.assertEqual(prompt.call_count, 1)

    def test_missing_noninteractive_store_and_source_errors(self):
        with self.assertRaisesRegex(DataError, '^CREDENTIAL_MISSING$'):
            credentials.resolve('tradier', 'sandbox', source='env', environment={})
        for source in ('prompt', 'auto'):
            prompt = Mock()
            with self.assertRaisesRegex(DataError, '^CREDENTIAL_PROMPT_UNAVAILABLE$'):
                credentials.resolve('ota', 'ota', source=source, environment={}, prompt=prompt)
            prompt.assert_not_called()
        store = Mock(return_value='synthetic-example')
        credentials.resolve('tradier', 'production', source='store', store=store)
        store.assert_called_once_with(provider='tradier', profile='production')
        with self.assertRaisesRegex(DataError, '^CREDENTIAL_SOURCE_INVALID$'):
            credentials.resolve('ota', 'ota', source='unknown')

    def test_prompt_tty_warning_and_safe_exceptions(self):
        reader = Mock()
        with self.assertRaisesRegex(DataError, '^CREDENTIAL_PROMPT_UNAVAILABLE$'):
            credentials.hidden_prompt(reader=reader, is_tty=lambda:False)
        reader.assert_not_called()
        def warn(*args):
            warnings.warn('synthetic-private-detail', getpass.GetPassWarning)
            self.fail('Echo fallback reached')
        with self.assertRaisesRegex(DataError, '^CREDENTIAL_PROMPT_UNAVAILABLE$'):
            credentials.hidden_prompt(reader=warn, is_tty=lambda:True)
        env = Mock()
        env.get.side_effect = RuntimeError('synthetic-private-detail')
        with self.assertRaisesRegex(DataError, '^CREDENTIAL_UNAVAILABLE$'):
            credentials.resolve('ota', 'ota', source='env', environment=env)

    def test_check_cli_redaction_and_failure(self):
        for suffix, outcome in (('ok','synthetic-example'), ('error', DataError('CREDENTIAL_MISSING'))):
            root = temp / ('credential-check-' + suffix)
            output = io.StringIO()
            with patch.object(credentials, 'resolve', **({'side_effect':outcome} if isinstance(outcome, Exception) else {'return_value':outcome})), redirect_stdout(output):
                self.assertEqual(main(['credential-check','--provider','tradier','--profile','sandbox','--credential-source','env'], root), 1 if suffix=='error' else 0)
            report = json.loads(next(root.glob('artifacts/agent-review/*.json')).read_text())
            self.assertNotIn('synthetic-example', output.getvalue()+json.dumps(report))
            self.assertEqual(report['checks'][0]['status'], 'failed' if suffix=='error' else 'passed')

    def test_cli_conflicting_flags_fail_before_dispatch(self):
        with patch('trading_scanner.tradier.run_probe') as probe, redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(['tradier-probe','--profile','sandbox','--symbol','SYNTH','--prompt-token','--credential-source','env'], temp)
        probe.assert_not_called()

    def test_ota_env_integration_and_auth_failure_no_fallback(self):
        from trading_scanner.ota_config import parse_config
        root = temp / 'credential-ota-env'
        (root / 'config').mkdir(parents=True)
        (root / 'config/ota-screener.json').write_text(json.dumps(parse_config('[{"field":"optionable","valueFilter":"BOOLEAN","valueChoices":"Yes","criteria":"true"}]')))
        with patch.object(credentials, 'resolve', return_value='synthetic-example') as resolve, patch('trading_scanner.ota_fetch.fetch_all', side_effect=DataError('OTA_AUTH_REJECTED')), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['ota-fetch','--profile','ota','--credential-source','env'],root), 1)
        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(resolve.call_args.kwargs['source'], 'env')
