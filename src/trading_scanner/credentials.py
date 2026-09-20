"""Explicit runtime credential resolution; no secret access on import.

The source is a user choice. Automatic mode only falls back on absence, never
on an empty value, invalid format, store failure or provider rejection.
"""
import getpass
import os
import re
import sys
import warnings

from .core import DataError

VARIABLES = {
    ('ota', 'ota'): 'SCANNER_OTA_TOKEN',
    ('tradier', 'sandbox'): 'SCANNER_TRADIER_SANDBOX_TOKEN',
    ('tradier', 'production'): 'SCANNER_TRADIER_PRODUCTION_TOKEN',
}
ERRORS = {'CREDENTIAL_SOURCE_INVALID', 'CREDENTIAL_PROFILE_INVALID',
          'CREDENTIAL_MISSING', 'CREDENTIAL_INVALID', 'CREDENTIAL_UNAVAILABLE',
          'CREDENTIAL_PROMPT_UNAVAILABLE'}


def hidden_prompt(message='Credential (hidden; not saved): ', *, reader=None, is_tty=None):
    if not (sys.stdin.isatty() if is_tty is None else is_tty()):
        raise DataError('CREDENTIAL_PROMPT_UNAVAILABLE')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            return (reader or getpass.getpass)(message)
    except (EOFError, OSError, getpass.GetPassWarning):
        raise DataError('CREDENTIAL_PROMPT_UNAVAILABLE') from None


def resolve(provider, profile, *, source, allow_prompt=False, environment=None,
            store=None, prompt=None):
    """Read only the selected key. Web/workers leave allow_prompt=False.

    Dependency injection is for synthetic tests, never a snapshot of the real
    environment. Returning a string preserves the existing provider API.
    """
    variable = VARIABLES.get((provider, profile))
    if variable is None:
        raise DataError('CREDENTIAL_PROFILE_INVALID')
    if source not in ('env', 'store', 'prompt', 'auto'):
        raise DataError('CREDENTIAL_SOURCE_INVALID')
    try:
        value = None
        if source in ('env', 'auto'):
            value = (os.environ if environment is None else environment).get(variable)
            if value is None and source == 'env':
                raise DataError('CREDENTIAL_MISSING')
        if source == 'store':
            if store is None:
                from .token_store import load_token
                store = load_token
            value = store(provider=provider, profile=None if provider == 'ota' else profile)
        if source == 'prompt' or (source == 'auto' and value is None):
            if not allow_prompt:
                raise DataError('CREDENTIAL_PROMPT_UNAVAILABLE')
            with warnings.catch_warnings():
                warnings.simplefilter('error', getpass.GetPassWarning)
                value = (prompt or hidden_prompt)()
        # Unlike paste input, injected environment values are not trimmed: an
        # accidental newline must fail rather than silently alter a secret.
        if not isinstance(value, str) or not re.fullmatch(r'[\x21-\x7e]{1,8192}', value):
            raise DataError('CREDENTIAL_INVALID')
        return value
    except DataError as exc:
        if len(exc.args) == 1 and exc.args[0] in ERRORS | {'TOKEN_STORE_EMPTY', 'TOKEN_STORE_UNAVAILABLE', 'OTA_TOKEN_INVALID', 'TRADIER_TOKEN_INVALID', 'OTA_PROMPT_UNAVAILABLE'}:
            raise
        raise DataError('CREDENTIAL_UNAVAILABLE') from None
    except Exception:
        raise DataError('CREDENTIAL_UNAVAILABLE') from None


def run_check(root, args):
    """User-run local format check; never authenticates or calls a provider."""
    from .dashboard import atomic_json
    from .run_ids import new_run_id
    from .scan_service import code_revision
    code = None
    try:
        resolve(args.provider, args.profile, source=args.credential_source)
    except DataError as exc:
        code = exc.args[0]
    report = {'schema_version': 1, 'run_id': new_run_id(),
              'code_revision': code_revision(), 'profile': args.profile,
              'checks': [{'name': 'credential_format', 'status': 'failed' if code else 'passed'}],
              'counts': {}, 'error_code': code}
    path = root / 'artifacts/agent-review' / (report['run_id'] + '.json')
    try:
        atomic_json(path, report)
    except OSError:
        print('LOG_UNAVAILABLE')
        return 1
    print(code or 'Credential loaded; format valid. Provider authentication not checked.')
    print(f'Agent review: {path}')
    return 1 if code else 0
