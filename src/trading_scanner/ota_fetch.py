"""Explicit user-run OTA pagination. No retries or redirects."""
from datetime import datetime, timezone
import getpass
import http.client
import json
import re
import ssl
from .run_ids import new_run_id
import warnings

from .core import DataError
from .ota import OtaSchemaError
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
DEFAULT_MAX_PAGES = 100
PATH = '/api/secure/screeners/criteria/results?rows=100&realtime=true&type=NON_OTC&view=criteria&sortField=symbol&sortOrder=asc&page=1'
MAX_RESPONSE = 2_000_000
from .credentials import ERRORS as CREDENTIAL_ERRORS

ERRORS = CREDENTIAL_ERRORS | {'THROTTLE_BUSY', 'THROTTLE_STATE_INVALID', 'THROTTLE_COOLDOWN_ACTIVE', 'THROTTLE_CIRCUIT_OPEN', 'OTA_CONFIG_INVALID', 'OTA_TOKEN_INVALID', 'OTA_PROMPT_UNAVAILABLE',
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
    from .credentials import hidden_prompt
    try:
        return hidden_prompt('Paste your OTA x-auth-token (hidden; not saved): ')
    except DataError:
        raise DataError('OTA_PROMPT_UNAVAILABLE') from None


def _fetch_page_once(criteria, token, *, page=1, page_size=DEFAULT_PAGE_SIZE, capture=None, governor=None):
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
        if governor is not None:
            governor.observe(status, response.getheader('Retry-After'))
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
        if capture is not None:
            capture(page, None, raw)
        try:
            payload = json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, RecursionError):
            raise OtaSchemaError('response', 'invalid_json') from None
        if capture is not None:
            capture(page, payload)
        from .ota_pipeline import raw_rows
        return raw_rows(payload, max_rows=page_size)
    except (OSError, http.client.HTTPException):
        raise DataError('OTA_NETWORK_ERROR') from None
    finally:
        if connection is not None:
            connection.close()


def fetch_page(criteria, token, *, page=1, page_size=DEFAULT_PAGE_SIZE, capture=None, governor=None):
    operation = lambda: _fetch_page_once(criteria, token, page=page, page_size=page_size, capture=capture, governor=governor)
    return operation() if governor is None else governor.call(operation, retries=0)


def fetch_all(criteria, token, *, page_size=DEFAULT_PAGE_SIZE, max_pages=DEFAULT_MAX_PAGES,
              progress=None, counts=None, capture=None, governor=None, cancel_check=None):
    request_path(1, page_size)
    if type(max_pages) is not int or not 1 <= max_pages <= 100:
        raise DataError('OTA_PAGINATION_INVALID')
    counts = counts if counts is not None else {}
    counts.update(pages_requested=0, pages_received=0, symbols_received=0)
    rows, seen = [], set()
    for page in range(1, max_pages + 1):
        if cancel_check: cancel_check()
        counts['pages_requested'] += 1
        batch = fetch_page(criteria, token, page=page, page_size=page_size, **({'capture': capture} if capture is not None else {}), **({'governor': governor} if governor is not None else {}))
        counts['pages_received'] += 1
        for row in batch:
            from .core import normalize_symbol
            symbol = normalize_symbol(row['symbol'])
            if symbol in seen:
                raise DataError('OTA_DUPLICATE_PAGE_SYMBOL')
            seen.add(symbol)
        rows.extend(batch)
        counts['symbols_received'] = len(rows)
        if progress is not None:
            progress.advance(page, counts=counts)
        if governor is not None:
            governor.unit_done()
        # Match the reference adapter: do not probe beyond a short final page.
        # A short page is not proof that the provider honored the requested size.
        if len(batch) < page_size:
            return rows
    raise DataError('OTA_PAGE_LIMIT')


def run_fetch(root, *, page_size=DEFAULT_PAGE_SIZE, max_pages=DEFAULT_MAX_PAGES, use_stored_token=False, credential_source=None,
              config_override=None, cancel_check=None, run_id=None, observer=None):
    from .cli import code_revision
    run_id = run_id or new_run_id()
    revision = code_revision()
    progress, count, code = None, 0, None
    schema_diagnostic = None
    request_config = None
    snapshot, profile = None, None
    from .dashboard import atomic_json
    from .ota_pipeline import raw_rows, write_processing, profile_summary
    destination = root / 'artifacts' / 'ota' / run_id
    pagination_counts = {'pages_requested': 0, 'pages_received': 0, 'symbols_received': 0}
    try:
        progress = RunProgress(root / 'artifacts' / 'logs', run_id, 'ota-fetch', 'ota', revision, observer=observer)
        progress.begin()
        progress.start('config_parse')
        try:
            if config_override is None:
                with (root / 'config' / 'ota-screener.json').open(encoding='utf-8') as stream:
                    raw = stream.read(MAX_INPUT + 1)
                if len(raw) > MAX_INPUT:
                    raise ValueError()
                config = json.loads(raw, object_pairs_hook=pairs)
            else:
                config = config_override
            checked = parse_config(json.dumps(config['criteria'], allow_nan=False))
            if config != checked:
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            raise DataError('OTA_CONFIG_INVALID') from None
        from .ota_config import config_identity
        request_config = {**config_identity(checked), 'page_size': page_size, 'max_pages': max_pages}
        progress.finish()
        print('Using pinned job configuration.' if config_override is not None else f"Using config: {(root / 'config/ota-screener.json').resolve()}")
        print(f"Criteria SHA256: {request_config['criteria_sha256']} | criteria={request_config['criteria_count']} enabled={request_config['enabled_count']} | page_size={page_size} max_pages={max_pages}")
        if cancel_check: cancel_check()
        progress.start('ota_auth')
        from .credentials import resolve
        token = resolve('ota', 'ota', source=credential_source or ('store' if use_stored_token else 'prompt'),
                        allow_prompt=cancel_check is None, prompt=prompt_token)
        progress.finish()
        destination.mkdir(parents=True, exist_ok=False)
        snapshot = {'schema_version': 2, 'source': 'ota', 'representation': 'ota_raw',
                    'acquisition_status': 'incomplete', 'coverage': 'incomplete',
                    'run_id': run_id, 'code_revision': revision,
                    'retrieved_at': datetime.now(timezone.utc).isoformat(),
                    'page_size': page_size, 'max_pages': max_pages, 'criteria': checked['criteria'],
                    'observation_timestamp': None, 'methodology': 'unverified', 'rows': []}
        atomic_json(destination / 'capture.json', snapshot)
        def capture(page, payload, raw_body=None):
            if raw_body is not None:
                page_dir = destination / 'pages'
                page_dir.mkdir(parents=True, exist_ok=True)
                with (page_dir / f'{page:03}.body.json').open('xb') as stream:
                    stream.write(raw_body)
                return
            # Persist the decoded JSON body before structural validation; no headers.
            atomic_json(destination / 'pages' / f'{page:03}.json',
                        {'page': page, 'retrieved_at': datetime.now(timezone.utc).isoformat(), 'payload': payload})
            batch = raw_rows(payload, max_rows=page_size)
            snapshot['rows'].extend(batch)
            atomic_json(destination / 'capture.json', snapshot)
        progress.start('ota_fetch', total=max_pages)
        try:
            from .throttling import Governor
            with Governor(root / 'artifacts/throttling', 'ota', progress=progress, **({'cancel_check':cancel_check} if cancel_check else {})) as governor:
                governor.plan(max_pages)
                rows = fetch_all(checked['criteria'], token, page_size=page_size,
                                 max_pages=max_pages, progress=progress, counts=pagination_counts, capture=capture, governor=governor, **({'cancel_check':cancel_check} if cancel_check else {}))
        finally:
            # No persistence; Python cannot promise secure erasure from memory.
            token = None
        count = len(rows)
        # Once exhaustion is observed, the actual number of pages is known.
        progress.total = pagination_counts['pages_received']
        progress.finish(counts=pagination_counts)
        if cancel_check: cancel_check()
        progress.start('ota_profile')
        snapshot.update(rows=rows, acquisition_status='completed_short_page', coverage='short_page_observed',
                        retrieved_at=datetime.now(timezone.utc).isoformat(), pages_received=pagination_counts['pages_received'])
        profile = write_processing(snapshot, destination)
        atomic_json(destination / 'capture.json', snapshot)
        atomic_json(destination / 'results.json', snapshot)
        progress.finish()
        print(f'Fetched {count} rows; stopped on a short page after {pagination_counts["pages_received"]} pages. Full coverage remains unverified.')
        print(f'Raw data: {destination / "results.json"}')
        print(f'Field profile: {destination / "field-profile.json"}')
        print(f'Normalized data: {destination / "normalized.json"}')
    except (Exception, KeyboardInterrupt) as exc:
        if progress:
            progress.pause()
        code = 'RUN_CANCELLED' if isinstance(exc, KeyboardInterrupt) else 'OTA_FETCH_FAILED'
        if isinstance(exc, DataError) and len(exc.args) == 1 and exc.args[0] in ERRORS:
            code = exc.args[0]
        if isinstance(exc, OtaSchemaError):
            schema_diagnostic = {'field': exc.field, 'reason': exc.reason}
            print(f'OTA schema check: {exc.field} / {exc.reason}')
        print(f'{code}: request stopped; no further retry or synthetic fallback.')
    if code and snapshot is not None:
        try:
            snapshot.update(acquisition_status='incomplete', coverage='incomplete', error_code=code)
            atomic_json(destination / 'capture.json', snapshot)
            profile = write_processing(snapshot, destination)
            print(f'Incomplete capture retained: {destination / "capture.json"}')
        except (OSError, ValueError, TypeError):
            pass
    try:
        review = root / 'artifacts' / 'agent-review'
        review.mkdir(parents=True, exist_ok=True)
        report = {'schema_version': 1, 'run_id': run_id, 'code_revision': revision,
                  'profile': 'ota', 'checks': [{'name': 'ota_paginated_fetch', 'status': 'failed' if code else 'passed'}],
                  'counts': {'rows': count, **pagination_counts}, 'error_code': code}
        if request_config is not None:
            report['request_config'] = request_config
        if profile is not None:
            report['data_profile'] = profile_summary(profile)
        if schema_diagnostic is not None:
            report['schema_diagnostic'] = schema_diagnostic
        if progress:
            progress.end(code, counts={'rows': count, **pagination_counts})
        path = review / f'{run_id}.json'
        path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(f'Agent review: {path}')
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
