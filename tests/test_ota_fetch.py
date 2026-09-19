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
from trading_scanner.ota_fetch import fetch_page, fetch_all, request_path, prompt_token, HOST, PATH, MAX_RESPONSE

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
            self.assertEqual(bool(list(root.glob('artifacts/ota/*/results.json'))), status == 200)

    def test_network_error_is_safe(self):
        connection = self.connection()
        connection.request.side_effect = OSError('synthetic-private-error')
        with patch('trading_scanner.ota_fetch.ssl.create_default_context'), patch('trading_scanner.ota_fetch.http.client.HTTPSConnection', return_value=connection):
            with self.assertRaisesRegex(DataError, '^OTA_NETWORK_ERROR$'):
                fetch_page(CRITERIA, 'synthetic-local-input')

    def test_reference_envelope_flows_through_transport(self):
        body = b'{"results":{"data":[{"symbol":"SYNTH","values":{"totalOptionsVolume":12}}],"total":1},"metadata":"synthetic-private-marker"}'
        with patch('trading_scanner.ota_fetch.ssl.create_default_context'), patch('trading_scanner.ota_fetch.http.client.HTTPSConnection', return_value=self.connection(body=body)):
            rows = fetch_page(CRITERIA, 'synthetic-local-input')
        self.assertEqual(rows[0]['totalOptionsVolume'], 12)
        self.assertNotIn('synthetic-private-marker', str(rows))

    def test_reference_envelope_empty_and_invalid(self):
        from trading_scanner.ota import parse_response
        self.assertEqual(parse_response({'results': {'data': []}}), [])
        for payload in ({'results': {'data': None}}, {'results': {'data': {}}},
                        {'results': []}, {'errors': []}, {'results': {'other': []}}):
            with self.assertRaises(DataError):
                parse_response(payload)

    def test_schema_diagnostic_contains_no_provider_values(self):
        root = temp / 'ota-schema-diagnostic'
        (root / 'config').mkdir(parents=True)
        (root / 'config' / 'ota-screener.json').write_text(json.dumps(parse_config(json.dumps(CRITERIA))))
        body = b'{"results":{"data":[{"symbol":"SYNTH","values":{"totalOpenInterest":"synthetic-private-marker"}}]}}'
        output = io.StringIO()
        with patch('trading_scanner.ota_fetch.prompt_token', return_value='synthetic-local-input'), patch('trading_scanner.ota_fetch.ssl.create_default_context'), patch('trading_scanner.ota_fetch.http.client.HTTPSConnection', return_value=self.connection(body=body)), redirect_stdout(output):
            self.assertEqual(main(['ota-fetch','--profile','ota'], root), 1)
        report = json.loads(next(root.glob('artifacts/agent-review/*.json')).read_text())
        self.assertEqual(report['schema_diagnostic'], {'field':'totalOpenInterest','reason':'non_integer'})
        self.assertNotIn('synthetic-private-marker', output.getvalue() + json.dumps(report))
        self.assertFalse(list(root.glob('artifacts/ota/*/results.json')))

    def test_paging_continues_past_full_pages_and_preserves_arguments(self):
        counts = {}
        progress = Mock()
        with patch('trading_scanner.ota_fetch.fetch_page', side_effect=[[{'symbol':'S01'}], [{'symbol':'S02'}], []]) as fetch:
            rows = fetch_all(CRITERIA, 'synthetic-local-input', page_size=1, counts=counts, progress=progress)
        self.assertEqual([r['symbol'] for r in rows], ['S01','S02'])
        self.assertEqual([c.kwargs for c in fetch.call_args_list],
                         [{'page':n, 'page_size':1} for n in (1,2,3)])
        self.assertTrue(all(c.args == (CRITERIA, 'synthetic-local-input') for c in fetch.call_args_list))
        self.assertEqual(counts, {'pages_requested':3, 'pages_received':3, 'symbols_received':2})
        self.assertEqual(progress.advance.call_count, 3)

    def test_full_pages_and_empty_first_page(self):
        with patch('trading_scanner.ota_fetch.fetch_page', side_effect=[[{'symbol':'S01'},{'symbol':'S02'}], []]):
            self.assertEqual(len(fetch_all(CRITERIA, 'synthetic-local-input', page_size=2)), 2)
        with patch('trading_scanner.ota_fetch.fetch_page', return_value=[]) as fetch:
            self.assertEqual(fetch_all(CRITERIA, 'synthetic-local-input'), [])
            fetch.assert_called_once()

    def test_duplicates_limits_and_midrun_expiry_stop(self):
        for responses, code in [([[{'symbol':'S01'}], [{'symbol':'S01'}]], 'OTA_DUPLICATE_PAGE_SYMBOL'),
                                ([[{'symbol':'S01'}], [{'symbol':'S02'}]], 'OTA_PAGE_LIMIT'),
                                ([[{'symbol':'S01'}], DataError('OTA_AUTH_REJECTED')], 'OTA_AUTH_REJECTED')]:
            with patch('trading_scanner.ota_fetch.fetch_page', side_effect=responses) as fetch:
                with self.assertRaisesRegex(DataError, code):
                    fetch_all(CRITERIA, 'synthetic-local-input', page_size=1, max_pages=2)
                self.assertEqual(fetch.call_count, 2)

    def test_page_size_and_path_validation(self):
        self.assertIn('rows=600&', request_path(2,600))
        self.assertTrue(request_path(2,600).endswith('page=2'))
        with patch('trading_scanner.ota_fetch.fetch_page') as fetch:
            for kwargs in ({'page_size':0}, {'page_size':601}, {'max_pages':0}, {'max_pages':101}):
                with self.assertRaises(DataError):
                    fetch_all(CRITERIA, 'synthetic-local-input', **kwargs)
            fetch.assert_not_called()
        from trading_scanner.ota import parse_response
        rows = [{'symbol':f'S{i}', 'values':{}} for i in range(600)]
        self.assertEqual(len(parse_response(rows, max_rows=600)),600)
        with self.assertRaises(DataError):
            parse_response(rows, max_rows=100)

    def test_cli_midrun_failure_never_publishes_partial_data(self):
        root = temp / 'ota-paging-failure'
        (root / 'config').mkdir(parents=True)
        (root / 'config' / 'ota-screener.json').write_text(json.dumps(parse_config(json.dumps(CRITERIA))))
        with patch('trading_scanner.ota_fetch.prompt_token', return_value='synthetic-local-input'), patch('trading_scanner.ota_fetch.fetch_page', side_effect=[[{'symbol':'S01'}], DataError('OTA_AUTH_REJECTED')]), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['ota-fetch','--profile','ota', '--page-size', '1'], root), 1)
        report = json.loads(next(root.glob('artifacts/agent-review/*.json')).read_text())
        self.assertEqual(report['counts']['pages_requested'],2)
        self.assertEqual(report['counts']['pages_received'],1)
        self.assertEqual(report['counts']['rows'],0)
        self.assertFalse(list(root.glob('artifacts/ota/*/results.json')))

    def test_short_page_does_not_probe_repeating_final_page(self):
        batch = [{'symbol':f'S{i}'} for i in range(77)]
        counts = {}
        with patch('trading_scanner.ota_fetch.fetch_page', return_value=batch) as fetch:
            self.assertEqual(fetch_all(CRITERIA, 'synthetic-local-input', counts=counts), batch)
        fetch.assert_called_once_with(CRITERIA, 'synthetic-local-input', page=1, page_size=100)
        self.assertEqual(counts['pages_requested'], 1)

    def test_default_pages_collect_hundreds_without_truncation(self):
        batches = [[{'symbol': f'S{i}'} for i in range(start, stop)]
                   for start, stop in ((0, 100), (100, 200), (200, 237))]
        with patch('trading_scanner.ota_fetch.fetch_page', side_effect=batches) as fetch:
            rows = fetch_all(CRITERIA, 'synthetic-local-input')
        self.assertEqual(len(rows), 237)
        self.assertEqual(len({row['symbol'] for row in rows}), 237)
        self.assertEqual([call.kwargs for call in fetch.call_args_list],
                         [{'page': page, 'page_size': 100} for page in (1, 2, 3)])

    def test_cli_defaults_to_hundred_for_fetch_and_daily(self):
        with patch('trading_scanner.ota_fetch.run_fetch', return_value=0) as fetch:
            self.assertEqual(main(['ota-fetch', '--profile', 'ota'], temp), 0)
        self.assertEqual(fetch.call_args.kwargs['page_size'], 100)
        with patch('trading_scanner.workflow.run_daily', return_value=0) as daily:
            self.assertEqual(main(['daily', '--profile', 'public'], temp), 0)
        self.assertEqual(daily.call_args.args[1].page_size, 100)
