"""Explicit user-run OTA pagination. No retries or redirects."""
from datetime import datetime, timezone
import getpass
import hashlib
import http.client
import json
import re
import ssl
import uuid
import warnings

from .core import DataError
from .ota import parse_response, OtaSchemaError
from .ota_config import MAX_INPUT, parse_config, pairs
from .progress import RunProgress

HOST = 'app.otatrade.com'
# Owner-requested browser-style compatibility header; not actual browser identity
# or a substitute for valid authentication. Keep deterministic for diagnostics.
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
              'AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/153.0.0.0 Safari/537.36')
BROWSER_HEADERS = {
    'Accept': '*/*',
    'Accept-Language': 'en-US,en;q=0.9,hi;q=0.8,es;q=0.7',
    'Origin': 'https://app.otatrade.com',
    'Referer': 'https://app.otatrade.com/app/screener',
    'Priority': 'u=1, i',
    'Sec-CH-UA': '"Google Chrome";v="153", "Not_A Brand";v="8", "Chromium";v="153"',
    'Sec-CH-UA-Mobile': '?0',
    'Sec-CH-UA-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'empty',
    'Sec-Fetch-Mode': 'cors',
    'Sec-Fetch-Site': 'same-origin',
    'User-Agent': USER_AGENT,
}
DEFAULT_PAGE_SIZE = 100
DEFAULT_MAX_PAGES = 50
PATH = '/api/secure/screeners/criteria/results?rows=100&realtime=true&type=NON_OTC&view=criteria&sortField=symbol&sortOrder=asc&page=1'
MAX_RESPONSE = 2_000_000
ERRORS = {'OTA_CONFIG_INVALID', 'OTA_TOKEN_INVALID', 'OTA_PROMPT_UNAVAILABLE',
          'OTA_AUTH_REJECTED', 'OTA_RATE_LIMITED', 'OTA_REDIRECT_REJECTED',
          'OTA_HTTP_ERROR', 'OTA_NETWORK_ERROR', 'OTA_RESPONSE_TOO_LARGE',
          'OTA_SCHEMA_INVALID', 'OTA_ENVELOPE_UNSUPPORTED', 'OTA_FETCH_FAILED', 'RUN_CANCELLED',
          'OTA_PAGINATION_INVALID', 'OTA_DUPLICATE_PAGE_SYMBOL', 'OTA_PAGE_LIMIT',
          'TOKEN_STORE_UNAVAILABLE', 'TOKEN_STORE_EMPTY'}


def request_path(page, page_size):
    if type(page) is not int or not 1 <= page <= 100 or type(page_size) is not int or not 1 <= page_size <= 600:
        raise DataError('OTA_PAGINATION_INVALID')
    return (f'/api/secure/screeners/criteria/results?rows={page_size}&realtime=true'
            f'&type=NON_OTC&view=criteria&sortField=symbol&sortOrder=asc&page={page}')


def prompt_token():
    # Raising the fallback warning prevents getpass from reading echoed input.
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        try:
            return getpass.getpass('Paste your OTA x-auth-token (hidden; not saved): ')
        except (getpass.GetPassWarning, EOFError):
            raise DataError('OTA_PROMPT_UNAVAILABLE') from None


def fetch_page(criteria, token, *, page=1, page_size=DEFAULT_PAGE_SIZE):
    path = request_path(page, page_size)
    if not isinstance(token, str) or not re.fullmatch(r'[\x21-\x7e]{1,8192}', token):
        raise DataError('OTA_TOKEN_INVALID')
    # Validate immediately before transport, including when called outside CLI.
    checked = parse_config(json.dumps(criteria, allow_nan=False))
    body = json.dumps(checked['criteria'], separators=(',', ':'), allow_nan=False).encode('utf-8')
    connection = None
    try:
        connection = http.client.HTTPSConnection(HOST, timeout=30, context=ssl.create_default_context())
        connection.request('POST', path, body=body,
                           # HTTP/2 pseudo-headers are represented by the HTTPS
                           # connection, method and path. http.client calculates
                           # Host and Content-Length; never reuse captured values.
                           headers={**BROWSER_HEADERS, 'x-auth-token': token,
                                    'Content-Type': 'application/json',
                                    'Accept-Encoding': 'identity'})
        response = connection.getresponse()
        status = response.status
        if status in (401, 403):
            raise DataError('OTA_AUTH_REJECTED')
        if status == 429:
            raise DataError('OTA_RATE_LIMITED')
        if 300 <= status < 400:
            raise DataError('OTA_REDIRECT_REJECTED')
        if status != 200:
            raise DataError('OTA_HTTP_ERROR')
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise DataError('OTA_RESPONSE_TOO_LARGE')
        try:
            payload = json.loads(raw, object_pairs_hook=pairs)
        except (ValueError, RecursionError):
            raise OtaSchemaError('response', 'invalid_json') from None
        return parse_response(payload, max_rows=page_size)
    except (OSError, http.client.HTTPException):
        raise DataError('OTA_NETWORK_ERROR') from None
    finally:
        if connection is not None:
            connection.close()


def fetch_all(criteria, token, *, page_size=DEFAULT_PAGE_SIZE, max_pages=DEFAULT_MAX_PAGES,
              progress=None, counts=None):
    request_path(1, page_size)
    if type(max_pages) is not int or not 1 <= max_pages <= 100:
        raise DataError('OTA_PAGINATION_INVALID')
    counts = counts if counts is not None else {}
    counts.update(pages_requested=0, pages_received=0, symbols_received=0)
    rows, seen = [], set()
    for page in range(1, max_pages + 1):
        counts['pages_requested'] += 1
        batch = fetch_page(criteria, token, page=page, page_size=page_size)
        counts['pages_received'] += 1
        for row in batch:
            if row['symbol'] in seen:
                raise DataError('OTA_DUPLICATE_PAGE_SYMBOL')
            seen.add(row['symbol'])
        rows.extend(batch)
        counts['symbols_received'] = len(rows)
        if progress is not None:
            progress.advance(page, counts=counts)
        # Match the reference adapter: do not probe beyond a short final page.
        # A short page is not proof that the provider honored the requested size.
        if len(batch) < page_size:
            return rows
    raise DataError('OTA_PAGE_LIMIT')


def run_fetch(root, *, page_size=DEFAULT_PAGE_SIZE, max_pages=DEFAULT_MAX_PAGES, use_stored_token=False):
    from .cli import code_revision
    run_id = uuid.uuid4().hex
    revision = code_revision()
    progress, count, code = None, 0, None
    schema_diagnostic = None
    pagination_counts = {'pages_requested': 0, 'pages_received': 0, 'symbols_received': 0}
    try:
        progress = RunProgress(root / 'artifacts' / 'logs', run_id, 'ota-fetch', 'ota', revision)
        progress.begin()
        progress.start('config_parse')
        try:
            with (root / 'config' / 'ota-screener.json').open(encoding='utf-8') as stream:
                raw = stream.read(MAX_INPUT + 1)
            if len(raw) > MAX_INPUT:
                raise ValueError()
            config = json.loads(raw, object_pairs_hook=pairs)
            checked = parse_config(json.dumps(config['criteria'], allow_nan=False))
            if config != checked:
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            raise DataError('OTA_CONFIG_INVALID') from None
        progress.finish()
        progress.start('ota_auth')
        if use_stored_token:
            from .token_store import load_token
            token = load_token()
        else:
            token = prompt_token()
        progress.finish()
        progress.start('ota_fetch', total=max_pages)
        try:
            rows = fetch_all(checked['criteria'], token, page_size=page_size,
                             max_pages=max_pages, progress=progress, counts=pagination_counts)
        finally:
            # No persistence; Python cannot promise secure erasure from memory.
            token = None
        count = len(rows)
        # Once exhaustion is observed, the actual number of pages is known.
        progress.total = pagination_counts['pages_received']
        progress.finish(counts=pagination_counts)
        progress.start('reports')
        destination = root / 'artifacts' / 'ota' / run_id
        destination.mkdir(parents=True, exist_ok=False)
        output = {'schema_version': 1, 'source': 'ota',
                  'retrieved_at': datetime.now(timezone.utc).isoformat(),
                  'observation_timestamp': None, 'page_size': page_size,
                  'pages_received': pagination_counts['pages_received'], 'coverage': 'short_page_observed',
                  'methodology': 'unverified',
                  'criteria_sha256': hashlib.sha256(json.dumps(checked['criteria'], sort_keys=True).encode()).hexdigest(),
                  'rows': rows}
        (destination / 'results.json').write_text(json.dumps(output, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        progress.finish()
        print(f'Fetched {count} rows; stopped on a short page after {pagination_counts["pages_received"]} pages. Full coverage remains unverified.')
        print(f'User data: {destination / "results.json"}')
    except (Exception, KeyboardInterrupt) as exc:
        code = 'RUN_CANCELLED' if isinstance(exc, KeyboardInterrupt) else 'OTA_FETCH_FAILED'
        if isinstance(exc, DataError) and len(exc.args) == 1 and exc.args[0] in ERRORS:
            code = exc.args[0]
        if isinstance(exc, OtaSchemaError):
            schema_diagnostic = {'field': exc.field, 'reason': exc.reason}
            print(f'OTA schema check: {exc.field} / {exc.reason}')
        print(f'{code}: request stopped; no retry or synthetic fallback.')
    try:
        review = root / 'artifacts' / 'agent-review'
        review.mkdir(parents=True, exist_ok=True)
        report = {'schema_version': 1, 'run_id': run_id, 'code_revision': revision,
                  'profile': 'ota', 'checks': [{'name': 'ota_paginated_fetch', 'status': 'failed' if code else 'passed'}],
                  'counts': {'rows': count, **pagination_counts}, 'error_code': code}
        if schema_diagnostic is not None:
            report['schema_diagnostic'] = schema_diagnostic
        path = review / f'{run_id}.json'
        path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(f'Agent review: {path}')
        if progress:
            progress.end(code, counts={'symbols_received': count})
    except OSError:
        code = code or 'OTA_FETCH_FAILED'
        print('OTA_FETCH_FAILED: could not finish diagnostic output.')
    finally:
        if progress:
            try:
                progress.close()
            except OSError:
                code = code or 'OTA_FETCH_FAILED'
    return 130 if code == 'RUN_CANCELLED' else 1 if code else 0
