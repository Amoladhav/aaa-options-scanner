"""Explicit user-run, single-page OTA connection check. No retries or redirects."""
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
from .ota import parse_rows
from .ota_config import MAX_INPUT, parse_config, pairs
from .progress import RunProgress

HOST = 'app.otatrade.com'
# Owner-requested browser-style compatibility header; not actual browser identity
# or a substitute for valid authentication. Keep deterministic for diagnostics.
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
              'AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/120.0.0.0 Safari/537.36')
PATH = '/api/secure/screeners/criteria/results?rows=100&realtime=true&type=NON_OTC&view=criteria&sortField=symbol&sortOrder=asc&page=1'
MAX_RESPONSE = 2_000_000
ERRORS = {'OTA_CONFIG_INVALID', 'OTA_TOKEN_INVALID', 'OTA_PROMPT_UNAVAILABLE',
          'OTA_AUTH_REJECTED', 'OTA_RATE_LIMITED', 'OTA_REDIRECT_REJECTED',
          'OTA_HTTP_ERROR', 'OTA_NETWORK_ERROR', 'OTA_RESPONSE_TOO_LARGE',
          'OTA_SCHEMA_INVALID', 'OTA_ENVELOPE_UNSUPPORTED', 'OTA_FETCH_FAILED', 'RUN_CANCELLED'}


def prompt_token():
    # Raising the fallback warning prevents getpass from reading echoed input.
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        try:
            return getpass.getpass('Paste your OTA x-auth-token (hidden; not saved): ')
        except (getpass.GetPassWarning, EOFError):
            raise DataError('OTA_PROMPT_UNAVAILABLE') from None


def fetch_page(criteria, token):
    if not isinstance(token, str) or not re.fullmatch(r'[\x21-\x7e]{1,8192}', token):
        raise DataError('OTA_TOKEN_INVALID')
    # Validate immediately before transport, including when called outside CLI.
    checked = parse_config(json.dumps(criteria, allow_nan=False))
    body = json.dumps(checked['criteria'], separators=(',', ':'), allow_nan=False).encode('utf-8')
    connection = None
    try:
        connection = http.client.HTTPSConnection(HOST, timeout=30, context=ssl.create_default_context())
        connection.request('POST', PATH, body=body,
                           headers={'x-auth-token': token, 'Content-Type': 'application/json',
                                    'Accept': 'application/json', 'Accept-Encoding': 'identity',
                                    'User-Agent': USER_AGENT})
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
            raise DataError('OTA_SCHEMA_INVALID') from None
        if not isinstance(payload, list):
            raise DataError('OTA_ENVELOPE_UNSUPPORTED')
        return parse_rows(payload)
    except (OSError, http.client.HTTPException):
        raise DataError('OTA_NETWORK_ERROR') from None
    finally:
        if connection is not None:
            connection.close()


def run_fetch(root):
    from .cli import code_revision
    run_id = uuid.uuid4().hex
    revision = code_revision()
    progress, count, code = None, 0, None
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
        token = prompt_token()
        progress.finish()
        progress.start('ota_fetch')
        try:
            rows = fetch_page(checked['criteria'], token)
        finally:
            # No persistence; Python cannot promise secure erasure from memory.
            token = None
        count = len(rows)
        progress.finish(counts={'symbols_received': count})
        progress.start('reports')
        destination = root / 'artifacts' / 'ota' / run_id
        destination.mkdir(parents=True, exist_ok=False)
        output = {'schema_version': 1, 'source': 'ota',
                  'retrieved_at': datetime.now(timezone.utc).isoformat(),
                  'observation_timestamp': None, 'page': 1, 'coverage': 'single_page_only',
                  'methodology': 'unverified',
                  'criteria_sha256': hashlib.sha256(json.dumps(checked['criteria'], sort_keys=True).encode()).hexdigest(),
                  'rows': rows}
        (destination / 'page.json').write_text(json.dumps(output, indent=2, allow_nan=False) + '\n', encoding='utf-8')
        progress.finish()
        print(f'Fetched {count} rows from page 1. Full coverage is not established.')
        print(f'User data: {destination / "page.json"}')
    except (Exception, KeyboardInterrupt) as exc:
        code = 'RUN_CANCELLED' if isinstance(exc, KeyboardInterrupt) else 'OTA_FETCH_FAILED'
        if isinstance(exc, DataError) and len(exc.args) == 1 and exc.args[0] in ERRORS:
            code = exc.args[0]
        print(f'{code}: request stopped; no retry or synthetic fallback.')
    try:
        review = root / 'artifacts' / 'agent-review'
        review.mkdir(parents=True, exist_ok=True)
        report = {'schema_version': 1, 'run_id': run_id, 'code_revision': revision,
                  'profile': 'ota', 'checks': [{'name': 'ota_single_page_fetch', 'status': 'failed' if code else 'passed'}],
                  'counts': {'rows': count}, 'error_code': code}
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
