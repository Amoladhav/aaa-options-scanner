from contextlib import redirect_stdout
from datetime import date
import io
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from offline_boundary import temp
from trading_scanner.core import DataError
from trading_scanner.tradier import (request_json, expiration_dates, underlying_quote, chain_rows,
                                     fetch_probe, run_probe, observation_date, MAX_RESPONSE)


def contracts(expiration='2026-10-16', kind='standard'):
    return [{'symbol': 'SYNTH' + side.upper(), 'underlying': 'SYNTH', 'root_symbol': 'SYNTH',
             'expiration_date': expiration, 'expiration_type': kind, 'contract_size': 100,
             'strike': 100, 'option_type': side, 'bid': 2, 'ask': 2.2,
             'bid_date': 123, 'ask_date': 124, 'volume': 400, 'open_interest': 1000} for side in ('call', 'put')]


class TradierTests(unittest.TestCase):
    def connection(self, status=200, body=b'{}'):
        connection = Mock()
        connection.getresponse.return_value.status = status
        connection.getresponse.return_value.read.return_value = body
        return connection

    def test_transport_fixed_host_readonly_and_profile(self):
        for profile, host in [('production', 'api.tradier.com'), ('sandbox', 'sandbox.tradier.com')]:
            connection = self.connection()
            with patch('trading_scanner.tradier.ssl.create_default_context'), patch('trading_scanner.tradier.http.client.HTTPSConnection', return_value=connection) as factory:
                self.assertEqual(request_json(profile, 'quote', {'symbols':'SYNTH', 'greeks':'false'}, 'synthetic-local-input'), {})
            self.assertEqual(factory.call_args.args, (host,))
            args, kwargs = connection.request.call_args
            self.assertEqual(args, ('GET', '/v1/markets/quotes?symbols=SYNTH&greeks=false'))
            self.assertEqual(set(kwargs['headers']), {'Authorization','Accept','Accept-Encoding','User-Agent'})
            connection.close.assert_called_once()
        with patch('trading_scanner.tradier.http.client.HTTPSConnection') as factory:
            for profile, endpoint, credential in [('unknown','quote','synthetic'), ('production','orders','synthetic'), ('sandbox','quote','invalid\nvalue')]:
                with self.assertRaises(DataError):
                    request_json(profile, endpoint, {'symbols':'SYNTH','greeks':'false'}, credential)
            factory.assert_not_called()

    def test_errors_no_retry_body_echo_or_redirect(self):
        for status, code in [(401,'AUTH_REJECTED'), (403,'AUTH_REJECTED'), (429,'RATE_LIMITED'), (302,'REDIRECT_REJECTED'), (500,'HTTP_ERROR')]:
            connection = self.connection(status, b'synthetic-private-body')
            with patch('trading_scanner.tradier.ssl.create_default_context'), patch('trading_scanner.tradier.http.client.HTTPSConnection', return_value=connection):
                with self.assertRaisesRegex(DataError, '^TRADIER_' + code + '$'):
                    request_json('sandbox', 'quote', {'symbols':'SYNTH','greeks':'false'}, 'synthetic-local-input')
            connection.request.assert_called_once()
            connection.getresponse.return_value.read.assert_not_called()
        for body, code in [(b'x'*(MAX_RESPONSE+1),'RESPONSE_TOO_LARGE'), (b'{"a":1,"a":2}','SCHEMA_INVALID'), (b'[]','SCHEMA_INVALID')]:
            with patch('trading_scanner.tradier.ssl.create_default_context'), patch('trading_scanner.tradier.http.client.HTTPSConnection', return_value=self.connection(body=body)):
                with self.assertRaisesRegex(DataError, '^TRADIER_' + code + '$'):
                    request_json('sandbox','quote',{'symbols':'SYNTH','greeks':'false'},'synthetic-local-input')

    def test_expirations_and_schema_fail_closed(self):
        today = date(2026,9,19)
        self.assertEqual(expiration_dates({'expirations':{'date':['2026-09-18','2026-10-16']}},today),['2026-10-16'])
        self.assertEqual(expiration_dates({'expirations':{'date':{'date':'2026-10-16','expiration_type':'standard'}}},today),['2026-10-16'])
        for payload in ({'expirations':{'date':['2026-10-16','2026-10-16']}}, {'expirations':{'date':None}}, {}):
            with self.assertRaisesRegex(DataError,'TRADIER_SCHEMA_INVALID'):
                expiration_dates(payload,today)
        with self.assertRaises(DataError):
            underlying_quote({'quotes':{'quote':{'symbol':'OTHER','type':'stock','last':100}}},'SYNTH')
        with self.assertRaises(DataError):
            underlying_quote({'quotes':{'quote':{'symbol':'SYNTH','type':'index','last':100}}},'SYNTH')
        rows = contracts()
        rows[0]['underlying']='OTHER'
        with self.assertRaises(DataError):
            chain_rows({'options':{'option':rows}},'SYNTH','2026-10-16')

    def test_skip_weekly_verify_standard_preserve_delay(self):
        responses = [{'expirations':{'date':['2026-09-25','2026-10-16']}},
                     {'quotes':{'quote':{'symbol':'SYNTH','type':'stock','last':101,'trade_date':123,'average_volume':2000000}}},
                     {'options':{'option':contracts('2026-09-25','weeklys')}},
                     {'options':{'option':contracts()}}]
        with patch('trading_scanner.tradier.request_json', side_effect=responses) as request:
            output = fetch_probe('sandbox','SYNTH','synthetic-local-input',as_of=date(2026,9,19))
        self.assertEqual(output['expiration'],'2026-10-16')
        self.assertAlmostEqual(output['call']['spread'],.2)
        self.assertEqual(output['market_data_mode'],'delayed_15_minutes')
        self.assertEqual(output['quote_freshness'],'unverified')
        self.assertEqual(output['underlying_average_volume'],2000000)
        self.assertEqual(output['underlying_average_volume_period'],'provider_90_day')
        self.assertEqual(request.call_count,4)
        self.assertTrue(request.call_args_list[0].args[2]['expirationType']=='true')

    def test_local_date_and_invalid_timestamps(self):
        self.assertEqual(observation_date('2026-09-19'),date(2026,9,19))
        with self.assertRaisesRegex(DataError,'TRADIER_INVALID_INPUT'):
            observation_date('20260919')
        with patch('trading_scanner.tradier.new_york_date',side_effect=DataError('DEPENDENCY_UNAVAILABLE')):
            with self.assertRaisesRegex(DataError,'DEPENDENCY_UNAVAILABLE'):
                observation_date()
        rows=contracts()
        rows[0]['bid_date']='synthetic-private-value'
        with self.assertRaisesRegex(DataError,'TRADIER_SCHEMA_INVALID'):
            chain_rows({'options':{'option':rows}},'SYNTH','2026-10-16')

    def test_probe_output_sanitized_and_failures_publish_no_data(self):
        for success in (True,False):
            root=temp/('tradier-probe-'+str(success))
            output=io.StringIO()
            result={'call':{'spread':.2},'put':{'spread':.3}}
            with patch('trading_scanner.token_store.load_token', return_value='synthetic-local-input') as load, patch('trading_scanner.tradier.fetch_probe', return_value=result, side_effect=None if success else DataError('TRADIER_AUTH_REJECTED')), redirect_stdout(output):
                self.assertEqual(run_probe(root,SimpleNamespace(profile='sandbox',symbol='SYNTH',as_of='2026-09-19')),0 if success else 1)
            load.assert_called_once_with(provider='tradier',profile='sandbox')
            report=json.loads(next(root.glob('artifacts/agent-review/*.json')).read_text())
            self.assertEqual(set(report),{'schema_version','run_id','code_revision','profile','checks','counts','error_code'})
            self.assertEqual(report['counts']['rows'],2 if success else 0)
            self.assertEqual(bool(list(root.glob('artifacts/tradier/*/*/atm-spreads.json'))),success)
            for path in root.glob('artifacts/**/*.json*'):
                self.assertNotIn('synthetic-local-input',path.read_text())
            self.assertNotIn('synthetic-local-input',output.getvalue())
