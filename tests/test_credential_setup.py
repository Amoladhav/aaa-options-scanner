"""Credential lifecycle verified only with an in-memory fake native store."""
from contextlib import redirect_stdout
import io
import json
import unittest
from unittest.mock import Mock,patch
from offline_boundary import temp
from trading_scanner.cli import main
from trading_scanner.core import DataError
from trading_scanner.credential_setup import manage,guidance

class SetupTests(unittest.TestCase):
    def setUp(self):
        self.values={};self.calls=[]
        def store(action,value=None,**kwargs):
            key=(kwargs['provider'],kwargs['profile']);self.calls.append((action,key))
            if action=='get': return self.values.get(key)
            if action=='set': self.values[key]=value
            if action=='delete': del self.values[key]
        self.store=store

    def test_add_replace_remove_and_profile_isolation(self):
        for provider,profile in (('ota','ota'),('tradier','sandbox'),('tradier','production')):
            manage(provider,profile,'add',store=self.store,prompt=lambda:'synthetic-example')
            self.assertTrue(manage(provider,profile,'status',store=self.store)['present'])
        manage('tradier','sandbox','replace',store=self.store,prompt=lambda:'synthetic-replacement')
        self.assertEqual(self.values['tradier','production'],'synthetic-example')
        manage('tradier','sandbox','remove',store=self.store)
        self.assertFalse(manage('tradier','sandbox','remove',store=self.store)['removed'])
        self.assertEqual(len(self.values),2)

    def test_preconditions_never_prompt_or_overwrite(self):
        prompt=Mock(return_value='synthetic-example')
        with self.assertRaisesRegex(DataError,'CREDENTIAL_NOT_FOUND'):
            manage('ota','ota','replace',store=self.store,prompt=prompt)
        manage('ota','ota','add',store=self.store,prompt=prompt)
        with self.assertRaisesRegex(DataError,'CREDENTIAL_EXISTS'):
            manage('ota','ota','add',store=self.store,prompt=prompt)
        self.assertEqual(prompt.call_count,1)
        with self.assertRaisesRegex(DataError,'CREDENTIAL_INVALID'):
            manage('ota','ota','replace',store=self.store,prompt=lambda:'invalid whitespace')
        self.assertEqual(self.values['ota',None],'synthetic-example')

    def test_guide_has_no_credential_access_and_invalid_profile_fails_early(self):
        store=Mock(side_effect=AssertionError('must not read'))
        self.assertEqual(guidance('tradier','sandbox')['variable'],'SCANNER_TRADIER_SANDBOX_TOKEN')
        with self.assertRaisesRegex(DataError,'CREDENTIAL_PROFILE_INVALID'):
            manage('tradier','ota','status',store=store)
        store.assert_not_called()

    def test_status_and_failures_never_expose_values(self):
        self.values['ota',None]='synthetic-private-marker'
        result=manage('ota','ota','status',store=self.store)
        self.assertEqual(result,{'present':True,'format_valid':True,'authentication_checked':False})
        for error in (RuntimeError('synthetic-private-marker'),DataError('synthetic-private-marker')):
            with self.assertRaisesRegex(DataError,'^CREDENTIAL_UNAVAILABLE$'):
                manage('ota','ota','status',store=Mock(side_effect=error))

    def test_cli_lifecycle_sanitized_reports_and_cancel(self):
        root=temp/'credential-setup-cli'
        with patch('trading_scanner.token_store.operate',side_effect=self.store),patch('trading_scanner.credential_setup.hidden_prompt',return_value='synthetic-private-marker'):
            for action in ('guide','add','status','replace','remove'):
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(['credential-manage',action,'--provider','ota','--profile','ota'],root),0)
                self.assertNotIn('synthetic-private-marker',output.getvalue())
            with patch('trading_scanner.credential_setup.hidden_prompt',side_effect=KeyboardInterrupt()),redirect_stdout(io.StringIO()):
                self.assertEqual(main(['credential-manage','add','--provider','ota','--profile','ota'],root),130)
        for path in root.glob('artifacts/agent-review/*.json'):
            text=path.read_text();self.assertNotIn('synthetic-private-marker',text)
            self.assertEqual(json.loads(text)['counts'],{})
