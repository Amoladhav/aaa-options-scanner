"""Pure, provider-independent ATM selection; never loads credentials or fetches data."""

from datetime import date
import math

from .core import DataError


def number(value):
    try:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    except OverflowError:
        return False


def quote_spread(row):
    """Dollar values are per share. Last-trade prices are deliberately unused."""
    bid, ask = row.get('bid'), row.get('ask')
    valid = number(bid) and number(ask)
    status = 'valid_unverified_freshness'
    if not valid:
        status = 'missing_or_invalid_quote'
    elif bid < 0 or ask < 0:
        status = 'negative_quote'
    elif bid > ask:
        status = 'crossed_quote'
    elif bid == 0 or ask == 0:
        status = 'zero_sided_quote'
    usable = status == 'valid_unverified_freshness'
    counts = {}
    for field in ('volume', 'open_interest'):
        value = row.get(field)
        if value is not None and (not number(value) or value < 0 or value != int(value)):
            raise DataError('CHAIN_INPUT_INVALID')
        counts[field] = None if value is None else int(value)
    return {
        'symbol': row.get('symbol'),
        'bid': bid if number(bid) else None,
        'ask': ask if number(ask) else None,
        'spread': ask - bid if usable else None,
        'spread_pct': ((ask - bid) / (ask / 2 + bid / 2)) * 100 if usable else None,
        'bid_date': row.get('bid_date'), 'ask_date': row.get('ask_date'),
        **counts,
        # A snapshot's current volume cannot establish a historical average.
        'average_volume': None, 'average_volume_status': 'unavailable',
        'status': status,
    }


def select_atm_spreads(rows, *, underlying_price, as_of):
    """Select earliest future provider-confirmed standard expiry, then shared ATM.

    ``as_of`` is an explicit New York calendar date. Same-day expirations are
    excluded for the daily after-close workflow. This does not classify dates
    by weekday: provider metadata handles holiday-shifted monthly expirations.
    Only ordinary 100-share stock/ETF contracts are supported; the caller must
    establish that the underlying is a stock/ETF, not an index or future.
    """
    if type(as_of) is not date or not number(underlying_price) or underlying_price <= 0:
        raise DataError('CHAIN_INPUT_INVALID')
    if not isinstance(rows, list) or len(rows) > 100000:
        raise DataError('CHAIN_INPUT_INVALID')
    eligible = []
    underliers = set()
    for row in rows:
        if not isinstance(row, dict):
            raise DataError('CHAIN_INPUT_INVALID')
        if row.get('expiration_type') != 'standard':
            continue
        try:
            expiration = date.fromisoformat(row['expiration_date'])
        except (KeyError, TypeError, ValueError):
            raise DataError('CHAIN_INPUT_INVALID') from None
        if expiration <= as_of:
            continue
        underlying = row.get('underlying')
        if not isinstance(underlying, str) or not underlying:
            raise DataError('CHAIN_INPUT_INVALID')
        underliers.add(underlying)
        eligible.append((expiration, row))
    if len(underliers) > 1:
        raise DataError('CHAIN_INPUT_INVALID')
    if not eligible:
        raise DataError('CHAIN_MONTHLY_UNAVAILABLE')
    expiration = min(item[0] for item in eligible)
    pairs = {}
    for expiry, row in eligible:
        if expiry != expiration:
            continue
        root = row.get('root_symbol')
        # Size alone cannot establish the deliverable. Unknown root is rejected.
        if (not isinstance(root, str) or
                root.replace('/', '.') != row['underlying'].replace('/', '.') or
                not number(row.get('contract_size')) or row['contract_size'] != 100):
            raise DataError('CHAIN_CONTRACT_UNSUPPORTED')
        strike, side = row.get('strike'), row.get('option_type')
        if not number(strike) or strike <= 0 or side not in ('call', 'put'):
            raise DataError('CHAIN_INPUT_INVALID')
        pair = pairs.setdefault(strike, {})
        if side in pair:
            raise DataError('CHAIN_CONTRACT_AMBIGUOUS')
        pair[side] = row
    shared = [strike for strike, pair in pairs.items() if set(pair) == {'call', 'put'}]
    if not shared:
        raise DataError('CHAIN_ATM_PAIR_UNAVAILABLE')
    strike = min(shared, key=lambda value: (abs(value - underlying_price), value))
    return {
        'expiration': expiration.isoformat(), 'expiration_type': 'standard',
        'expiration_marker': '*', 'underlying_price': underlying_price,
        'strike': strike, 'as_of': as_of.isoformat(),
        'selection': 'nearest_shared_strike_lower_tie',
        'call': quote_spread(pairs[strike]['call']),
        'put': quote_spread(pairs[strike]['put']),
    }
