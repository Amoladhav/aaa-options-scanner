from copy import deepcopy
import unittest

import offline_boundary
from trading_scanner.core import DataError
from trading_scanner.ota import parse_rows, FIELDS


class OtaSchemaTests(unittest.TestCase):
    def setUp(self):
        # Invented values only; no copied authenticated response or token.
        self.rows = [{"symbol": "SYNTH", "values": {
            "meanIvPcnt": 45.0, "ivHi1YrPcnt": 80.0, "ivLow1YrPcnt": 20.0,
            "spreadLiquidityPcnt": 90.0, "totalOpenInterest": 10000,
            "totalOptionsVolume": 1200, "ivGauge": 2, "optionable": 1}}]

    def test_vendor_fields_preserved_without_metric_aliases(self):
        before = deepcopy(self.rows)
        result = parse_rows(self.rows)
        self.assertEqual(result[0], {"symbol": "SYNTH", **self.rows[0]['values']})
        self.assertEqual(self.rows, before)
        self.assertNotIn('iv_rank', result[0])
        self.assertNotIn('iv_percentile', result[0])

    def test_unknown_fields_dropped(self):
        self.rows[0]['values']['markers'] = {'private': 'synthetic-sensitive-marker'}
        self.rows[0]['unneeded'] = 'synthetic-sensitive-marker'
        parsed = parse_rows(self.rows)
        self.assertEqual(set(parsed[0]), {'symbol', *FIELDS})
        self.assertNotIn('synthetic-sensitive-marker', str(parsed))

    def test_missing_null_and_zero(self):
        self.rows[0]['values'] = {'totalOpenInterest': 0, 'totalOptionsVolume': None}
        result = parse_rows(self.rows)[0]
        self.assertEqual(result['totalOpenInterest'], 0)
        self.assertTrue(all(result[k] is None for k in FIELDS if k != 'totalOpenInterest'))

    def test_iv_over_100_is_not_clipped(self):
        self.rows[0]['values']['meanIvPcnt'] = 160.5
        self.assertEqual(parse_rows(self.rows)[0]['meanIvPcnt'], 160.5)

    def test_invalid_values_fail_with_fixed_code(self):
        for field, value in [('meanIvPcnt', float('nan')), ('ivHi1YrPcnt', float('inf')),
                             ('meanIvPcnt', True), ('meanIvPcnt', -1), ('meanIvPcnt', 10**400),
                             ('totalOpenInterest', 1.5), ('totalOptionsVolume', '1200'),
                             ('ivGauge', False), ('optionable', -1)]:
            rows = deepcopy(self.rows)
            rows[0]['values'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(DataError, '^OTA_SCHEMA_INVALID$'):
                parse_rows(rows)

    def test_envelope_invalid_rows_and_duplicates_rejected(self):
        for rows in [{'data': self.rows}, [None], [{'symbol': None, 'values': {}}],
                     [{'symbol': 'SYNTH', 'values': []}], self.rows * 2, self.rows * 101]:
            with self.subTest(rows_type=type(rows).__name__), self.assertRaises(DataError):
                parse_rows(rows)
        with self.assertRaises(DataError):
            parse_rows([{'symbol': 'BRK.B', 'values': {}}, {'symbol': 'BRK-B', 'values': {}}])

    def test_empty_page_is_valid_without_coverage_claim(self):
        self.assertEqual(parse_rows([]), [])
