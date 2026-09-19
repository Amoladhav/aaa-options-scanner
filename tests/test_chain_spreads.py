from copy import deepcopy
from datetime import date
import unittest

from trading_scanner.chain_spreads import quote_spread, select_atm_spreads
from trading_scanner.core import DataError


def chain(expiration='2026-06-18', kind='standard'):
    return [dict(symbol=f'DEMO-{strike}-{side}', underlying='DEMO',
                 root_symbol='DEMO', strike=strike, option_type=side,
                 expiration_date=expiration, expiration_type=kind,
                 contract_size=100, bid=3.1, ask=3.2)
            for strike in (95, 100, 105) for side in ('call', 'put')]


class ChainSpreadTests(unittest.TestCase):
    def select(self, rows, spot=100.2, day=date(2026, 6, 1)):
        return select_atm_spreads(rows, underlying_price=spot, as_of=day)

    def test_provider_monthly_metadata_handles_holiday_and_ignores_weekly(self):
        result = self.select(chain() + chain('2026-06-05', 'weekly'))
        self.assertEqual(result['expiration'], '2026-06-18')
        self.assertEqual(result['strike'], 100)
        self.assertAlmostEqual(result['call']['spread'], .1)
        self.assertAlmostEqual(result['put']['spread_pct'], 100 * .1 / 3.15)
        self.assertEqual(result['call']['status'], 'valid_unverified_freshness')

    def test_tie_lower_shared_strike_and_no_quote_driven_strike_change(self):
        rows = chain()
        rows[2]['bid'] = None
        result = self.select(rows, spot=102.5)
        self.assertEqual(result['strike'], 100)
        self.assertIsNone(result['call']['spread'])
        rows = [r for r in rows if not (r['strike'] == 100 and r['option_type'] == 'put')]
        self.assertEqual(self.select(rows)['strike'], 105)

    def test_same_day_excluded_and_nearest_expiry_missing_pair_fails(self):
        self.assertEqual(self.select(chain() + chain('2026-07-17'), day=date(2026, 6, 18))['expiration'], '2026-07-17')
        with self.assertRaisesRegex(DataError, 'CHAIN_ATM_PAIR_UNAVAILABLE'):
            self.select([r for r in chain() if r['option_type'] == 'call'] + chain('2026-07-17'))

    def test_unsupported_and_ambiguous_contracts_fail_closed(self):
        for field, value in [('root_symbol', 'DEMO1'), ('contract_size', 10), ('root_symbol', None)]:
            rows = chain()
            rows[0][field] = value
            with self.assertRaisesRegex(DataError, 'CHAIN_CONTRACT_UNSUPPORTED'):
                self.select(rows)
        with self.assertRaisesRegex(DataError, 'CHAIN_CONTRACT_AMBIGUOUS'):
            self.select(chain() + [deepcopy(chain()[0])])

    def test_invalid_quotes_never_become_zero_spreads(self):
        for bid, ask, status in [(None, 1, 'missing_or_invalid_quote'),
                                 (float('nan'), 1, 'missing_or_invalid_quote'),
                                 (True, 1, 'missing_or_invalid_quote'),
                                 (-1, 1, 'negative_quote'), (2, 1, 'crossed_quote'),
                                 (0, 1, 'zero_sided_quote'), (0, 0, 'zero_sided_quote')]:
            result = quote_spread({'bid': bid, 'ask': ask, 'lastPrice': 5})
            self.assertEqual(result['status'], status)
            self.assertIsNone(result['spread'])
            self.assertIsNone(result['spread_pct'])
        self.assertEqual(quote_spread({'bid': 1, 'ask': 1})['spread'], 0)

    def test_mixed_underliers_and_invalid_selection_inputs(self):
        rows = chain()
        rows[0]['underlying'] = 'OTHER'
        with self.assertRaisesRegex(DataError, 'CHAIN_INPUT_INVALID'):
            self.select(rows)
        with self.assertRaisesRegex(DataError, 'CHAIN_INPUT_INVALID'):
            self.select(chain(), spot=float('inf'))
        with self.assertRaisesRegex(DataError, 'CHAIN_MONTHLY_UNAVAILABLE'):
            self.select(chain(kind='weekly'))

    def test_contract_counts_preserve_missing_and_do_not_invent_average(self):
        result = quote_spread({'bid': 1, 'ask': 2, 'volume': 0, 'open_interest': 123.0})
        self.assertEqual(result['volume'], 0)
        self.assertEqual(result['open_interest'], 123)
        self.assertIsNone(result['average_volume'])
        self.assertEqual(result['average_volume_status'], 'unavailable')
        missing = quote_spread({'bid': 1, 'ask': 2})
        self.assertIsNone(missing['volume'])
        self.assertIsNone(missing['open_interest'])
        for field in ('volume', 'open_interest'):
            for value in (-1, 1.5, True, float('nan'), '123'):
                with self.assertRaisesRegex(DataError, 'CHAIN_INPUT_INVALID'):
                    quote_spread({'bid': 1, 'ask': 2, field: value})
