from contextlib import redirect_stdout
import getpass
import io
import json
import unittest
from unittest.mock import Mock, patch
import warnings

from offline_boundary import temp
from trading_scanner.cli import main
from trading_scanner.core import DataError
from trading_scanner.ota_config import parse_config
from trading_scanner.ota_fetch import fetch_page, prompt_token, HOST, PATH, MAX_RESPONSE

CRITERIA = [{'field':'optionable', 'valueFilter':'BOOLEAN', 'valueChoices':'Yes', 'criteria':'true'}]


class OtaFetchTests(unittest.TestCase):
    def connection(self, status=200, body=b'[]'):
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = status
        response.read.return_value = body
        return connection

    def test_exact_request_and_no_cookie_or_redirect_transport(self):
        connection = self.connection(body=b'[{"symbol":"SYNTH","values":{"totalOptionsVolume":12}}]')
        with patch('trading_scanner.ota_fetch.ssl.create_default_context', return_value=object()), patch('trading_scanner.ota_fetch.http.client.HTTPSConnection', return_value=connection) as constructor:
            rows = fetch_page(CRITERIA, 'synthetic-local-input')
        self.assertEqual(rows[0]['totalOptionsVolume'], 12)
        self.assertEqual(constructor.call_args.args, (HOST,))
        self.assertEqual(constructor.call_args.kwargs['timeout'], 30)
        args, kwargs = connection.request.call_args
        self.assertEqual(args, ('POST', PATH))
        self.assertEqual(json.loads(kwargs['body']), CRITERIA)
        self.assertEqual(set(kwargs['headers']), {'x-auth-token','Content-Type','Accept','Accept-Encoding','User-Agent',
                         'Accept-Language','Origin','Referer','Priority','Sec-CH-UA','Sec-CH-UA-Mobile',
                         'Sec-CH-UA-Platform','Sec-Fetch-Dest','Sec-Fetch-Mode','Sec-Fetch-Site'})
        self.assertEqual(kwargs['headers']['Accept'], '*/*')
        self.assertEqual(kwargs['headers']['Accept-Encoding'], 'identity')
        self.assertEqual(kwargs['headers']['Origin'], 'https://app.otatrade.com')
        self.assertEqual(kwargs['headers']['Referer'], 'https://app.otatrade.com/app/screener')
        self.assertIn('v="153"', kwargs['headers']['Sec-CH-UA'])
        self.assertEqual(kwargs['headers']['User-Agent'],
                         'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                         'AppleWebKit/537.36 (KHTML, like Gecko) '
                         'Chrome/153.0.0.0 Safari/537.36')
        connection.request.assert_called_once()
        connection.close.assert_called_once()

    def test_http_failures_do_not_read_body_or_retry(self):
        for status, code in [(401,'OTA_AUTH_REJECTED'), (403,'OTA_AUTH_REJECTED'),
                             (429,'OTA_RATE_LIMITED'), (302,'OTA_REDIRECT_REJECTED'), (500,'OTA_HTTP_ERROR')]:
            connection = self.connection(status)
            with patch('trading_scanner.ota_fetch.ssl.create_default_context'), patch('trading_scanner.ota_fetch.http.client.HTTPSConnection', return_value=connection):
                with self.assertRaisesRegex(DataError, code):
                    fetch_page(CRITERIA, 'synthetic-local-input')
            connection.getresponse.return_value.read.assert_not_called()
            connection.request.assert_called_once()
            connection.close.assert_called_once()

    def test_response_limits_and_envelope_fail_closed(self):
        for body, code in [(b'x'*(MAX_RESPONSE+1),'OTA_RESPONSE_TOO_LARGE'),
                           (b'{"data":[]}', 'OTA_ENVELOPE_UNSUPPORTED'),
                           (b'<html>synthetic</html>', 'OTA_SCHEMA_INVALID')]:
            with patch('trading_scanner.ota_fetch.ssl.create_default_context'), patch('trading_scanner.ota_fetch.http.client.HTTPSConnection', return_value=self.connection(body=body)):
                with self.assertRaisesRegex(DataError, code):
                    fetch_page(CRITERIA, 'synthetic-local-input')

    def test_invalid_token_never_connects_and_prompt_never_echoes(self):
        with patch('trading_scanner.ota_fetch.http.client.HTTPSConnection') as connection:
            for value in ('', 'has space', 'has\nnewline'):
                with self.assertRaisesRegex(DataError, 'OTA_TOKEN_INVALID'):
                    fetch_page(CRITERIA, value)
            connection.assert_not_called()
        def unavailable(*args):
            warnings.warn('synthetic prompt unavailable', getpass.GetPassWarning)
            self.fail('Echo fallback must not run')
        with patch('trading_scanner.ota_fetch.getpass.getpass', side_effect=unavailable):
            with self.assertRaisesRegex(DataError, 'OTA_PROMPT_UNAVAILABLE'):
                prompt_token()

    def test_cli_success_and_failure_sanitized(self):
        for suffix, status in [('success',200), ('failure',401)]:
            root = temp / ('ota-fetch-' + suffix)
            (root / 'config').mkdir(parents=True)
            (root / 'config' / 'ota-screener.json').write_text(json.dumps(parse_config(json.dumps(CRITERIA))))
            output = io.StringIO()
            with patch('trading_scanner.ota_fetch.prompt_token', return_value='synthetic-local-input'), patch('trading_scanner.ota_fetch.ssl.create_default_context'), patch('trading_scanner.ota_fetch.http.client.HTTPSConnection', return_value=self.connection(status)), redirect_stdout(output):
                self.assertEqual(main(['ota-fetch','--profile','ota'], root), 0 if status == 200 else 1)
            report = json.loads(next(root.glob('artifacts/agent-review/*.json')).read_text())
            self.assertEqual(report['error_code'], None if status == 200 else 'OTA_AUTH_REJECTED')
            self.assertEqual(set(report), {'schema_version','run_id','code_revision','profile','checks','counts','error_code'})
            self.assertNotIn('synthetic-local-input', output.getvalue())
            for path in root.glob('artifacts/**/*.json*'):
                self.assertNotIn('synthetic-local-input', path.read_text())
            self.assertEqual(bool(list(root.glob('artifacts/ota/*/page.json'))), status == 200)

    def test_network_error_is_safe(self):
        connection = self.connection()
        connection.request.side_effect = OSError('synthetic-private-error')
        with patch('trading_scanner.ota_fetch.ssl.create_default_context'), patch('trading_scanner.ota_fetch.http.client.HTTPSConnection', return_value=connection):
            with self.assertRaisesRegex(DataError, '^OTA_NETWORK_ERROR$'):
                fetch_page(CRITERIA, 'synthetic-local-input')
