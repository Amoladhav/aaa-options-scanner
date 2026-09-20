from throttle_fixtures import virtual_throttle_time
from argparse import Namespace
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime
import io
import json
import unittest
from unittest.mock import patch

from offline_boundary import temp
from trading_scanner.core import DataError
from trading_scanner.dashboard import combine, synthetic_ota, attach_tradier
from trading_scanner.demo import make_snapshot
from trading_scanner.tradier_batch import master_universe, master_id, run_batch


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(virtual_throttle_time())
        self.snapshot = make_snapshot()
        self.snapshot['profile'] = 'public'
        # Legal provider symbols; includes share-class mapping.
        self.snapshot['universe'] = [{'symbol': s, 'group': 'stock'} for s in ('AAA', 'BRK-B', 'CCC')]

    def probe(self, symbol):
        return {'schema_version': 1, 'source': 'tradier', 'profile': 'production',
                'symbol': symbol, 'retrieved_at': '2026-09-19T22:00:00+00:00',
                'atm_strike': 100, 'expiration': '2026-10-16', 'expiration_type': 'standard',
                'call': {'strike': 100}, 'put': {'strike': 100}}

    def run_fixture(self, name, fail=None):
        root = temp / name
        root.mkdir()
        source = root / 'snapshot.json'
        source.write_text(json.dumps(self.snapshot))
        args = Namespace(profile='production', snapshot=source, prompt_token=True, as_of='2026-09-19')
        visited = []
        def fetch(profile, symbol, credential, **kwargs):
            visited.append(symbol)
            kwargs['before_request']()
            kwargs['capture']('quote', {'symbols': symbol, 'greeks': 'false'}, b'{"unknown": "kept"}')
            if fail and len(visited) == 2:
                if fail == 'cancel':
                    raise KeyboardInterrupt()
                raise DataError(fail)
            return self.probe(symbol)
        with patch('trading_scanner.tradier_batch.fetch_probe', side_effect=fetch), \
             patch('trading_scanner.token_store.prompt_api_key', return_value='synthetic-local-input') as prompt, \
             patch('trading_scanner.token_store.load_token') as store, redirect_stdout(io.StringIO()):
            code = run_batch(root, args)
        prompt.assert_called_once()
        store.assert_not_called()
        path = next(root.glob('artifacts/tradier/production/*/batch.json'))
        batch = json.loads(path.read_text())
        report = json.loads(next(root.glob('artifacts/agent-review/*.json')).read_text())
        self.assertNotIn('AAA', json.dumps(report))
        self.assertNotIn('synthetic-local-input', json.dumps(batch))
        self.assertTrue((path.parent / 'symbols/0000/capture/001-quote.body.json').exists())
        return code, batch, report, visited

    def test_all_master_symbols_and_shared_class_mapping(self):
        code, batch, report, visited = self.run_fixture('batch-complete')
        self.assertEqual(code, 0)
        self.assertEqual(visited, ['AAA', 'BRK/B', 'CCC'])
        self.assertEqual(batch['status'], 'completed')
        self.assertEqual(len(batch['rows']), 3)
        self.assertEqual(report['counts']['symbols_received'], 3)
        self.assertEqual(batch['master_id'], master_id(master_universe(self.snapshot)))
        result = {'profile': 'public', 'master_id': batch['master_id'],
                  'combined': [{'symbol': row['symbol']} for row in batch['rows']]}
        attach_tradier(result, [batch])
        self.assertTrue(all(row['tradier_atm_strike'] == 100 for row in result['combined']))
        with self.assertRaises(DataError):
            attach_tradier(result, [batch, batch])
        with self.assertRaises(DataError):
            attach_tradier({**result, 'master_id': 'different'}, [batch])

    def test_symbol_failure_continues_and_preserves_master(self):
        code, batch, report, visited = self.run_fixture('batch-partial', 'TRADIER_SCHEMA_INVALID')
        self.assertEqual(code, 1)
        self.assertEqual(len(visited), 3)
        self.assertEqual(batch['status'], 'completed_with_errors')
        self.assertEqual(report['counts']['symbols_failed'], 1)
        result = {'profile': 'public', 'master_id': batch['master_id'],
                  'combined': [{'symbol': row['symbol']} for row in batch['rows']]}
        attach_tradier(result, [batch])
        self.assertEqual(result['combined'][1]['tradier_status'], 'failed')
        self.assertIsNone(result['combined'][1]['tradier_atm_strike'])

    def test_auth_failure_stops_and_checkpoints_unattempted(self):
        code, batch, report, visited = self.run_fixture('batch-auth', 'TRADIER_AUTH_REJECTED')
        self.assertEqual(code, 1)
        self.assertEqual(len(visited), 2)
        self.assertEqual(batch['status'], 'incomplete')
        self.assertEqual([row['status'] for row in batch['rows']], ['returned', 'failed', 'not_attempted'])
        self.assertEqual(report['error_code'], 'TRADIER_AUTH_REJECTED')
        self.assertEqual(report['counts']['symbols_failed'], 1)

    def test_master_dashboard_retains_price_exclusions(self):
        snapshot = make_snapshot()
        # The extra member lacks price history and must remain visible with provider fields.
        snapshot['universe'].append({'symbol': 'MISSING', 'group': 'stock'})
        ota = synthetic_ota(snapshot)
        ota['rows'].append({'symbol': 'MISSING', 'totalOpenInterest': 12345})
        result = combine(snapshot, ota, now=datetime.fromisoformat(ota['retrieved_at']))
        self.assertEqual(len(result['combined']), len(snapshot['universe']))
        row = next(row for row in result['combined'] if row['symbol'] == 'MISSING')
        self.assertEqual(row['crs_status'], 'excluded')
        self.assertEqual(row['review_status'], 'unranked')
        self.assertEqual(row['totalOpenInterest'], 12345)
        self.assertIsNone(row['rank'])
        self.assertNotIn('MISSING', {row['symbol'] for row in result['ranked']})

    def test_cancel_keeps_prior_success_and_remaining_members(self):
        code, batch, report, visited = self.run_fixture('batch-cancel', 'cancel')
        self.assertEqual(code, 130)
        self.assertEqual([row['status'] for row in batch['rows']], ['returned', 'failed', 'not_attempted'])
        self.assertEqual(report['error_code'], 'RUN_CANCELLED')

    def test_request_gate_runs_for_every_http_request(self):
        from datetime import date
        from trading_scanner.tradier import fetch_probe
        payloads = [{'expirations': {'date': ['2026-10-16']}},
                    {'quotes': {'quote': {'symbol': 'AAA', 'type': 'stock', 'last': 100}}},
                    {'options': {'option': [
                        {'symbol': 'AAA' + side.upper(), 'underlying': 'AAA', 'root_symbol': 'AAA',
                         'expiration_date': '2026-10-16', 'expiration_type': 'standard',
                         'option_type': side, 'strike': 100, 'contract_size': 100,
                         'bid': 1, 'ask': 2} for side in ('call', 'put')]}}]
        with patch('trading_scanner.tradier.request_json', side_effect=payloads) as request, \
             patch('trading_scanner.throttling.Governor.call') as gate:
            fetch_probe('production', 'AAA', 'synthetic-local-input', as_of=date(2026, 9, 19),
                        before_request=gate)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(gate.call_count, 3)
