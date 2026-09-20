"""Opt-in OS credential storage. Never invoked by demo/cached/default fetch paths."""
from contextlib import redirect_stderr, redirect_stdout
import logging
import re
import sys
from .run_ids import new_run_id

from .core import DataError
from .progress import RunProgress

SERVICE = 'aaa-options-scanner.ota'
ENTRY = 'session-token'


def backend():
    # Instantiate only a native backend; do not discover plugins, plaintext
    # fallbacks or a user-selected backend from arbitrary configuration.
    if sys.platform == 'win32':
        from keyring.backends.Windows import WinVaultKeyring
        return WinVaultKeyring()
    if sys.platform == 'darwin':
        from keyring.backends.macOS import Keyring
        return Keyring()
    if sys.platform.startswith('linux'):
        from keyring.backends.SecretService import Keyring
        return Keyring()
    raise DataError('TOKEN_STORE_UNAVAILABLE')


def operate(action, value=None, *, provider='ota', profile=None):
    from .scan_service import DiscardOutput
    if provider not in ('ota', 'tradier') or (provider == 'tradier' and profile not in ('sandbox', 'production')) or (provider == 'ota' and profile is not None):
        raise DataError('TOKEN_STORE_UNAVAILABLE')
    service = SERVICE if provider == 'ota' else f'aaa-options-scanner.tradier.{profile}'
    entry = ENTRY if provider == 'ota' else 'api-key'
    old_disable = logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        with redirect_stdout(DiscardOutput()), redirect_stderr(DiscardOutput()):
            store = backend()
            if action == 'get':
                return store.get_password(service, entry)
            if action == 'set':
                return store.set_password(service, entry, value)
            if action == 'delete':
                return store.delete_password(service, entry)
            raise DataError('TOKEN_STORE_UNAVAILABLE')
    except Exception:
        raise DataError('TOKEN_STORE_UNAVAILABLE') from None
    finally:
        logging.disable(old_disable)


def valid_token(value, *, provider='ota'):
    if isinstance(value, str):
        value = value.strip()
    if not isinstance(value, str) or not re.fullmatch(r'[\x21-\x7e]{1,8192}', value):
        raise DataError('TRADIER_TOKEN_INVALID' if provider == 'tradier' else 'OTA_TOKEN_INVALID')
    return value


def load_token(*, provider='ota', profile=None):
    value = operate('get') if provider == 'ota' and profile is None else operate('get', provider=provider, profile=profile)
    if value is None:
        raise DataError('TOKEN_STORE_EMPTY')
    return valid_token(value, provider=provider)


def run_store(root, action, *, provider='ota', profile=None):
    from .cli import code_revision
    from .ota_fetch import prompt_token
    progress, code = None, None
    try:
        if provider not in ('ota', 'tradier') or (provider == 'tradier' and profile not in ('sandbox', 'production')):
            raise DataError('TOKEN_STORE_UNAVAILABLE')
        progress = RunProgress(root / 'artifacts' / 'logs', new_run_id(), 'ota-token' if provider == 'ota' else 'tradier-token', 'ota' if provider == 'ota' else profile, code_revision())
        progress.begin()
        progress.start('token_store')
        if action == 'set':
            value = valid_token(prompt_token() if provider == 'ota' else prompt_api_key(), provider=provider)
            try:
                operate('set', value) if provider == 'ota' else operate('set', value, provider=provider, profile=profile)
            finally:
                value = None
            print('Stored in the OS credential store. Session expiry still applies.' if provider == 'ota' else f'Stored Tradier key in the OS credential store for {profile}.')
        elif action == 'delete':
            operate('delete') if provider == 'ota' else operate('delete', provider=provider, profile=profile)
            print('Removed the local stored credential. This does not revoke it at the provider.')
        else:
            raise DataError('TOKEN_STORE_UNAVAILABLE')
        progress.finish()
    except (Exception, KeyboardInterrupt) as exc:
        if progress:
            progress.pause()
        code = 'RUN_CANCELLED' if isinstance(exc, KeyboardInterrupt) else 'TOKEN_STORE_UNAVAILABLE'
        if isinstance(exc, DataError) and exc.args[0] in ('TOKEN_STORE_EMPTY','OTA_TOKEN_INVALID','TRADIER_TOKEN_INVALID','OTA_PROMPT_UNAVAILABLE'):
            code = exc.args[0]
        if code in ('OTA_TOKEN_INVALID', 'TRADIER_TOKEN_INVALID'):
            print(f'{code}: paste only the key, without a header prefix, quotes or internal whitespace.')
        else:
            print(f'{code}: OS storage unavailable; check keyring and an unlocked native store.')
            if provider == 'tradier':
                print('For a user-run probe without storage, use tradier-probe --prompt-token with the matching profile.')
    finally:
        if progress:
            try:
                progress.end(code)
                progress.close()
            except OSError:
                code = code or 'LOG_UNAVAILABLE'
    return 130 if code == 'RUN_CANCELLED' else 1 if code else 0


def prompt_api_key(*, save=True):
    from .credentials import hidden_prompt
    label = 'saved to OS store' if save else 'not saved'
    try:
        return hidden_prompt(f'Paste your Tradier API key (hidden; {label}): ')
    except DataError:
        raise DataError('TOKEN_STORE_UNAVAILABLE') from None
