"""Synthetic end-to-end ingestion, profiling and replay checks."""
from throttle_fixtures import virtual_throttle_time
from copy import deepcopy
from contextlib import redirect_stdout
from unittest.mock import Mock, patch
import io
import json
import unittest
from offline_boundary import temp
from trading_scanner.cli import main
from trading_scanner.ota_config import parse_config
from trading_scanner.ota_pipeline import raw_rows, profile_rows, normalize_snapshot
from trading_scanner.dashboard import ota_checked
from trading_scanner.core import DataError

CRITERIA = [{'field':'optionable','valueFilter':'BOOLEAN','valueChoices':'Yes','criteria':'true'}]

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(virtual_throttle_time())

    def test_lossless_rows_and_profile_partition(self):
        values = [-1, '45.2', '', '  ', None, 'N/A', True, {'nested': 1}, [1,2]]
        rows = [{'symbol':f'S{i}', 'values':{'meanIvPcnt':v, 'unknown':v}} for i,v in enumerate(values)]
        rows.append({'symbol':'LAST', 'values':{}})
        original = deepcopy(rows)
        self.assertEqual(raw_rows(rows), original)
        profile = profile_rows(rows)['fields']['meanIvPcnt']
        self.assertEqual(profile['missing'],1)
        self.assertEqual(profile['number'],1)
        self.assertEqual(profile['string'],4)
        self.assertEqual(profile['numeric_strings'],1)
        self.assertEqual(profile['blank_strings'],2)
        self.assertEqual(profile['other_strings'],1)
        self.assertEqual(profile['negative_numbers'],1)
        self.assertEqual(profile['minimum'],-1)
        self.assertEqual(profile['maximum'],45.2)
        self.assertEqual(sum(profile[k] for k in ('missing','null','number','string','boolean','object','array')),len(rows))
        self.assertEqual(rows, original)

    def snapshot(self, rows, status='completed_short_page'):
        return {'representation':'ota_raw','acquisition_status':status, 'source':'ota',
                'retrieved_at':'2026-09-19T22:00:00+00:00', 'coverage':'short_page_observed', 'rows':rows}

    def test_normalization_keeps_parsed_negative_separate_and_unknown_reason(self):
        raw = self.snapshot([{'symbol':'SYNTH','values':{'meanIvPcnt':-1,'totalOptionsVolume':'12.5',
            'totalOpenInterest':'1200', 'ivGauge':'N/A','daysToEarnings':'','ivLow1YrPcnt':None}}])
        original = deepcopy(raw)
        result = normalize_snapshot(raw)['rows'][0]
        self.assertEqual(result['parsed_values']['meanIvPcnt'],-1)
        self.assertIsNone(result['meanIvPcnt'])
        self.assertEqual(result['totalOpenInterest'],1200)
        self.assertEqual(result['field_status']['totalOptionsVolume'],'invalid_count')
        self.assertEqual(result['field_status']['ivGauge'],'non_numeric')
        self.assertEqual(result['field_status']['daysToEarnings'],'blank')
        self.assertEqual(result['field_status']['ivLow1YrPcnt'],'null')
        self.assertEqual(result['field_status']['ivHi1YrPcnt'],'missing')
        self.assertEqual(ota_checked(raw,'public')['rows'][0]['field_status'], result['field_status'])
        self.assertEqual(raw,original)
        with self.assertRaises(DataError):
            ota_checked({**raw, 'acquisition_status':'incomplete'},'public')

    def setup_root(self, name):
        root = temp / name
        (root/'config').mkdir(parents=True)
        (root/'config/ota-screener.json').write_text(json.dumps(parse_config(json.dumps(CRITERIA))))
        return root

    def connection(self, body, status=200):
        response = Mock(status=status)
        response.read.return_value = body
        connection = Mock()
        connection.getresponse.return_value = response
        return connection

    def test_fetch_preserves_body_and_raw_and_replays_without_transport(self):
        root = self.setup_root('raw-fetch')
        body = b'{"results":{"data":[{"symbol":"SYNTH","values":{"meanIvPcnt":-1,"unknown":"private-fixture","ivGauge":"N/A"}}]}}'
        with patch('trading_scanner.ota_fetch.prompt_token',return_value='synthetic-local-input'), patch('trading_scanner.ota_fetch.ssl.create_default_context'), patch('trading_scanner.ota_fetch.http.client.HTTPSConnection',return_value=self.connection(body)), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['ota-fetch','--profile','ota'],root),0)
        path = next(root.glob('artifacts/ota/*/results.json'))
        self.assertEqual((path.parent/'pages/001.body.json').read_bytes(),body)
        raw = json.loads(path.read_text())
        self.assertEqual(raw['rows'][0]['values']['meanIvPcnt'],-1)
        self.assertEqual(raw['rows'][0]['values']['unknown'],'private-fixture')
        self.assertTrue((path.parent/'field-profile.json').exists())
        before = path.read_bytes()
        with patch('trading_scanner.ota_fetch.http.client.HTTPSConnection') as network, patch('trading_scanner.ota_fetch.prompt_token') as prompt, redirect_stdout(io.StringIO()):
            self.assertEqual(main(['ota-process','--input',str(path)],root),0)
        network.assert_not_called(); prompt.assert_not_called()
        self.assertEqual(path.read_bytes(),before)
        for review in root.glob('artifacts/agent-review/*.json'):
            self.assertNotIn('private-fixture',review.read_text())
            self.assertNotIn('synthetic-local-input',review.read_text())

    def test_interrupted_fetch_keeps_partial_capture_but_no_complete_result(self):
        root = self.setup_root('raw-partial')
        body = b'[{"symbol":"SYNTH","values":{"meanIvPcnt":"N/A"}}]'
        with patch('trading_scanner.ota_fetch.prompt_token',return_value='synthetic-local-input'), patch('trading_scanner.ota_fetch.ssl.create_default_context'), patch('trading_scanner.ota_fetch.http.client.HTTPSConnection',side_effect=[self.connection(body),self.connection(b'',401)]), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['ota-fetch','--profile','ota','--page-size','1'],root),1)
        path = next(root.glob('artifacts/ota/*/capture.json'))
        capture = json.loads(path.read_text())
        self.assertEqual(capture['acquisition_status'],'incomplete')
        self.assertEqual(capture['rows'][0]['values']['meanIvPcnt'],'N/A')
        self.assertFalse((path.parent/'results.json').exists())
        self.assertFalse((path.parent/'normalized.json').exists())
        self.assertEqual(json.loads((path.parent/'field-profile.json').read_text())['rows'],1)
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['ota-process','--input',str(path)],root),0)
        self.assertFalse(list(root.glob('artifacts/ota-processing/*/normalized.json')))

    def test_malformed_body_is_retained_but_never_published(self):
        root = self.setup_root('raw-malformed')
        body = b'{not valid json}'
        with patch('trading_scanner.ota_fetch.prompt_token', return_value='synthetic-local-input'), patch('trading_scanner.ota_fetch.ssl.create_default_context'), patch('trading_scanner.ota_fetch.http.client.HTTPSConnection',return_value=self.connection(body)), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['ota-fetch','--profile','ota'],root),1)
        capture = next(root.glob('artifacts/ota/*/capture.json'))
        self.assertEqual((capture.parent/'pages/001.body.json').read_bytes(),body)
        self.assertEqual(json.loads(capture.read_text())['acquisition_status'],'incomplete')
        self.assertFalse((capture.parent/'results.json').exists())

    def test_profile_review_excludes_unknown_names_ranges_and_values(self):
        from trading_scanner.ota_pipeline import profile_summary
        profile = profile_rows([{'symbol':'PRIVATE','values':{'private-field':'private-value', 'meanIvPcnt':-123.45}}])
        review = profile_summary(profile)
        self.assertEqual(review['fields']['meanIvPcnt']['negative_numbers'],1)
        for excluded in ('private-field','private-value','PRIVATE','minimum','maximum','123.45'):
            self.assertNotIn(excluded,json.dumps(review))
