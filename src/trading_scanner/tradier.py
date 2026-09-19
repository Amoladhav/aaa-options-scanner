"""Explicit user-run, read-only Tradier ATM probe. No account or order endpoints.

The native credential-store reader is invoked only by run_probe, never on import.
Monthly status comes from provider contract metadata, not calendar guessing.
"""
from datetime import date, datetime, timezone
import http.client
import json
import math
import re
import ssl
from urllib.parse import urlencode
import uuid

from .core import DataError
from .ota_config import pairs
from .progress import RunProgress

HOSTS = {'production': 'api.tradier.com', 'sandbox': 'sandbox.tradier.com'}
MAX_RESPONSE = 5_000_000
MAX_CHAINS = 32
ERRORS = {'TRADIER_INVALID_INPUT', 'TRADIER_TOKEN_INVALID', 'TRADIER_AUTH_REJECTED',
          'TRADIER_RATE_LIMITED', 'TRADIER_REDIRECT_REJECTED', 'TRADIER_HTTP_ERROR',
          'TRADIER_NETWORK_ERROR', 'TRADIER_RESPONSE_TOO_LARGE', 'TRADIER_SCHEMA_INVALID',
          'TRADIER_MONTHLY_UNVERIFIED', 'TRADIER_NO_ATM_PAIR', 'TRADIER_FETCH_FAILED',
          'TOKEN_STORE_UNAVAILABLE', 'TOKEN_STORE_EMPTY', 'RUN_CANCELLED', 'DEPENDENCY_UNAVAILABLE'}


def symbol_checked(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z]{1,6}(?:[./-][A-Za-z])?', value):
        raise DataError('TRADIER_INVALID_INPUT')
    return value.upper().replace('.', '/').replace('-', '/')


def request_json(profile, endpoint, params, credential):
    allowed = {'expirations': ('options/expirations', {'symbol', 'includeAllRoots', 'expirationType'}),
               'quote': ('quotes', {'symbols', 'greeks'}),
               'chain': ('options/chains', {'symbol', 'expiration', 'greeks'})}
    if profile not in HOSTS or endpoint not in allowed or set(params) != allowed[endpoint][1]:
        raise DataError('TRADIER_INVALID_INPUT')
    if not isinstance(credential, str) or not re.fullmatch(r'[\x21-\x7e]{1,8192}', credential):
        raise DataError('TRADIER_TOKEN_INVALID')
    path = '/v1/markets/' + allowed[endpoint][0] + '?' + urlencode(params)
    connection = None
    try:
        connection = http.client.HTTPSConnection(HOSTS[profile], timeout=30, context=ssl.create_default_context())
        connection.request('GET', path, headers={'Authorization': 'Bearer ' + credential,
                           'Accept': 'application/json', 'Accept-Encoding': 'identity',
                           'User-Agent': 'aaa-options-scanner/1'})
        response = connection.getresponse()
        if response.status in (401, 403):
            raise DataError('TRADIER_AUTH_REJECTED')
        if response.status == 429:
            raise DataError('TRADIER_RATE_LIMITED')
        if 300 <= response.status < 400:
            raise DataError('TRADIER_REDIRECT_REJECTED')
        if response.status != 200:
            raise DataError('TRADIER_HTTP_ERROR')
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise DataError('TRADIER_RESPONSE_TOO_LARGE')
        try:
            result = json.loads(raw, object_pairs_hook=pairs)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        except (ValueError, RecursionError):
            raise DataError('TRADIER_SCHEMA_INVALID') from None
    except (OSError, http.client.HTTPException):
        raise DataError('TRADIER_NETWORK_ERROR') from None
    finally:
        if connection is not None:
            connection.close()


def expiration_dates(payload, as_of):
    """Accept date list or enriched date records; contract metadata is final proof."""
    try:
        values = payload['expirations']['date']
        if isinstance(values, (str, dict)):
            values = [values]
        if not isinstance(values, list) or not values or len(values) > 1000:
            raise ValueError()
        output = []
        for item in values:
            raw = item if isinstance(item, str) else item['date']
            parsed = date.fromisoformat(raw)
            if parsed.isoformat() != raw:
                raise ValueError()
            if parsed > as_of:
                output.append(raw)
        if len(set(output)) != len(output):
            raise ValueError()
        return sorted(output)
    except (KeyError, TypeError, ValueError):
        raise DataError('TRADIER_SCHEMA_INVALID') from None


def underlying_quote(payload, symbol):
    try:
        row = payload['quotes']['quote']
        if isinstance(row, list) and len(row) == 1:
            row = row[0]
        price = row['last']
        if row.get('type') not in ('stock', 'etf') or symbol_checked(row['symbol']) != symbol or type(price) not in (int, float) or not math.isfinite(price) or price <= 0:
            raise ValueError()
        timestamp = row.get('trade_date')
        if timestamp is not None and (type(timestamp) is not int or timestamp < 0):
            raise ValueError()
        average_volume = row.get('average_volume')
        if average_volume is not None and (type(average_volume) not in (int, float) or not math.isfinite(average_volume) or average_volume < 0):
            raise ValueError()
        return {'last': price, 'trade_date': timestamp, 'average_volume': average_volume}
    except (KeyError, TypeError, ValueError):
        raise DataError('TRADIER_SCHEMA_INVALID') from None


def chain_rows(payload, symbol, expiration):
    try:
        rows = payload['options']['option']
        if isinstance(rows, dict):
            rows = [rows]
        if not isinstance(rows, list) or not rows or len(rows) > 25000:
            raise ValueError()
        keys = ('symbol', 'underlying', 'root_symbol', 'strike', 'option_type', 'expiration_date',
                'expiration_type', 'contract_size', 'bid', 'ask', 'bid_date', 'ask_date', 'volume', 'open_interest')
        result = []
        for row in rows:
            if not isinstance(row, dict) or row.get('expiration_date') != expiration or symbol_checked(row.get('underlying')) != symbol:
                raise ValueError()
            if row.get('expiration_type') not in ('standard', 'weeklys', 'weekly', 'eom', 'quarterlys', 'quarterly'):
                raise ValueError()
            for field in ('bid_date', 'ask_date'):
                value = row.get(field)
                if value is not None and (type(value) is not int or value < 0):
                    raise ValueError()
            if not isinstance(row.get('symbol'), str) or not re.fullmatch(r'[A-Z0-9./]{1,40}', row['symbol']):
                raise ValueError()
            result.append({key: row.get(key) for key in keys})
        return result
    except (KeyError, TypeError, ValueError):
        raise DataError('TRADIER_SCHEMA_INVALID') from None


def fetch_probe(profile, symbol, credential, *, as_of, progress=None, counts=None):
    from .chain_spreads import select_atm_spreads
    symbol = symbol_checked(symbol)
    counts = {} if counts is None else counts
    if progress:
        progress.start('tradier_expirations')
    expirations = expiration_dates(request_json(profile, 'expirations',
        {'symbol': symbol, 'includeAllRoots': 'false', 'expirationType': 'true'}, credential), as_of)
    if progress:
        progress.finish()
        progress.start('tradier_quote')
    quote = underlying_quote(request_json(profile, 'quote', {'symbols': symbol, 'greeks': 'false'}, credential), symbol)
    if progress:
        progress.finish()
        progress.start('tradier_chain', total=max(1, min(MAX_CHAINS, len(expirations))))
    for index, expiration in enumerate(expirations[:MAX_CHAINS], 1):
        rows = chain_rows(request_json(profile, 'chain',
            {'symbol': symbol, 'expiration': expiration, 'greeks': 'false'}, credential), symbol, expiration)
        counts['chains_received'] = index
        if progress:
            progress.advance(index)
        if not any(row['expiration_type'] == 'standard' for row in rows):
            continue
        try:
            result = select_atm_spreads(rows, underlying_price=quote['last'], as_of=as_of)
        except DataError:
            raise DataError('TRADIER_NO_ATM_PAIR') from None
        if progress:
            progress.total = index
            progress.finish()
        return {'schema_version': 1, 'source': 'tradier', 'profile': profile, 'symbol': symbol,
                'retrieved_at': datetime.now(timezone.utc).isoformat(),
                'market_data_mode': 'delayed_15_minutes' if profile == 'sandbox' else 'brokerage_feed',
                'quote_freshness': 'unverified', 'underlying_trade_date': quote['trade_date'],
                'underlying_average_volume': quote['average_volume'],
                'underlying_average_volume_period': 'provider_90_day', **result}
    raise DataError('TRADIER_MONTHLY_UNVERIFIED')


def new_york_date():
    # Lazy import: timezone discovery may consult environment and the OS tzdata.
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        return datetime.now(ZoneInfo('America/New_York')).date()
    except ZoneInfoNotFoundError:
        raise DataError('DEPENDENCY_UNAVAILABLE') from None


def observation_date(override=None):
    if override is not None:
        try:
            parsed = date.fromisoformat(override)
            if parsed.isoformat() != override:
                raise ValueError()
            return parsed
        except (TypeError, ValueError):
            raise DataError('TRADIER_INVALID_INPUT') from None
    return new_york_date()


def run_probe(root, args):
    from .cli import code_revision
    from .dashboard import atomic_json
    from .token_store import load_token
    run_id, revision = uuid.uuid4().hex, code_revision()
    progress, code, counts = None, None, {'chains_received': 0, 'rows': 0}
    try:
        if args.profile not in HOSTS:
            raise DataError('TRADIER_INVALID_INPUT')
        symbol = symbol_checked(args.symbol)
        as_of = observation_date(getattr(args, 'as_of', None))
        progress = RunProgress(root / 'artifacts' / 'logs', run_id, 'tradier-probe', args.profile, revision)
        progress.begin()
        progress.start('tradier_auth')
        credential = load_token(provider='tradier', profile=args.profile)
        progress.finish()
        try:
            # Same-day expiry is excluded using the New York trading date.
            result = fetch_probe(args.profile, symbol, credential, as_of=as_of,
                                 progress=progress, counts=counts)
        finally:
            credential = None
        progress.start('reports')
        output = root / 'artifacts' / 'tradier' / args.profile / run_id / 'atm-spreads.json'
        atomic_json(output, result)
        counts['rows'] = 2
        progress.finish()
        print(f'User data: {output}')
        print('ATM bid-ask spread draft saved; quote freshness remains unverified.')
    except (Exception, KeyboardInterrupt) as exc:
        code = 'RUN_CANCELLED' if isinstance(exc, KeyboardInterrupt) else 'TRADIER_FETCH_FAILED'
        if isinstance(exc, DataError) and len(exc.args) == 1 and exc.args[0] in ERRORS:
            code = exc.args[0]
        print(f'{code}: request stopped; no retry or synthetic fallback.')
    try:
        if progress:
            progress.end(code, counts={'symbols_received': counts['rows']})
            progress.close()
            progress = None
        report = {'schema_version': 1, 'run_id': run_id, 'code_revision': revision,
                  'profile': args.profile if args.profile in HOSTS else 'unknown',
                  'checks': [{'name': 'tradier_atm_probe', 'status': 'failed' if code else 'passed'}],
                  'counts': counts, 'error_code': code}
        path = root / 'artifacts' / 'agent-review' / f'{run_id}.json'
        atomic_json(path, report)
        print(f'Agent review: {path}')
    except OSError:
        code = code or 'TRADIER_FETCH_FAILED'
        print('TRADIER_FETCH_FAILED: could not finish diagnostic output.')
    finally:
        if progress:
            try:
                progress.close()
            except OSError:
                code = code or 'TRADIER_FETCH_FAILED'
    return 130 if code == 'RUN_CANCELLED' else 1 if code else 0
