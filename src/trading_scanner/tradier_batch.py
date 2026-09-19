"""User-run master-universe collection with per-symbol checkpoints and paced requests."""
from datetime import datetime, timezone
import hashlib
import json
import time
import uuid

from .core import DataError, normalize_universe
from .dashboard import atomic_json, read_json
from .progress import RunProgress, SAFE_ERRORS
from .tradier import (HOSTS, ERRORS, symbol_checked, observation_date, fetch_probe,
                      capture_writer)


def master_universe(snapshot):
    # Membership, not successful rankings or OTA screening, drives acquisition.
    if not isinstance(snapshot, dict) or snapshot.get('profile') != 'public':
        raise DataError('TRADIER_INVALID_INPUT')
    rows = snapshot.get('universe')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 2000:
        raise DataError('TRADIER_INVALID_INPUT')
    return normalize_universe(rows)


def master_id(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class RequestPacer:
    """One sequential process, below documented limits; other clients share quota."""
    def __init__(self, profile, clock=time.monotonic, sleep=time.sleep):
        self.interval = 0.65 if profile == 'production' else 1.1
        self.clock, self.sleep, self.next_at = clock, sleep, 0.0

    def __call__(self):
        delay = self.next_at - self.clock()
        if delay > 0:
            self.sleep(delay)
        self.next_at = self.clock() + self.interval


def run_batch(root, args):
    from .cli import code_revision
    from .token_store import load_token, prompt_api_key, valid_token
    from .workflow import newest
    run_id, revision = uuid.uuid4().hex, code_revision()
    progress, state, destination, credential, code = None, None, None, None, None
    counts = {'master_symbols': 0, 'symbols_requested': 0, 'symbols_received': 0, 'symbols_failed': 0, 'requests': 0}
    try:
        if args.profile not in HOSTS:
            raise DataError('TRADIER_INVALID_INPUT')
        progress = RunProgress(root / 'artifacts/logs', run_id, 'tradier-fetch', args.profile, revision)
        progress.begin()
        progress.start('snapshot_load')
        path = args.snapshot or newest(root.glob('artifacts/runs/public/*/snapshot.json'))
        snapshot = read_json(path)
        master = master_universe(snapshot)
        counts['master_symbols'] = len(master)
        as_of = observation_date(getattr(args, 'as_of', None))
        destination = root / 'artifacts/tradier' / args.profile / run_id
        destination.mkdir(parents=True, exist_ok=False)
        atomic_json(destination / 'master.json', {'schema_version': 1, 'rows': master,
                    'membership_observed_at': snapshot.get('membership_observed_at'),
                    'price_as_of': snapshot.get('as_of')})
        state = {'schema_version': 1, 'representation': 'tradier_batch', 'source': 'tradier',
                 'profile': args.profile, 'run_id': run_id, 'code_revision': revision,
                 'master_id': master_id(master), 'as_of': as_of.isoformat(),
                 'started_at': datetime.now(timezone.utc).isoformat(), 'status': 'incomplete',
                 'rows': [{'symbol': row['symbol'], 'status': 'not_attempted', 'error_code': None,
                           'result': None} for row in master]}
        atomic_json(destination / 'batch.json', state)
        progress.finish()
        progress.start('tradier_auth')
        credential = (valid_token(prompt_api_key(save=False), provider='tradier')
                      if args.prompt_token else load_token(provider='tradier', profile=args.profile))
        progress.finish()
        progress.start('tradier_batch', total=len(master))
        pacer = RequestPacer(args.profile)
        # Stop systemic failures instead of sending the same failing request hundreds of times.
        local_errors = {'TRADIER_INVALID_INPUT', 'TRADIER_SCHEMA_INVALID',
                        'TRADIER_MONTHLY_UNVERIFIED', 'TRADIER_NO_ATM_PAIR'}
        for index, row in enumerate(state['rows']):
            counts['symbols_requested'] += 1
            row['status'] = 'in_progress'
            atomic_json(destination / 'batch.json', state)
            capture, capture_state = capture_writer(destination / 'symbols' / f'{index:04}',
                                                     args.profile, run_id, revision)
            def before_request():
                pacer()
                counts['requests'] += 1
                progress.advance(index, counts=counts)
            try:
                provider_symbol = symbol_checked(row['symbol'])
                row['provider_symbol'] = provider_symbol
                result = fetch_probe(args.profile, provider_symbol, credential, as_of=as_of,
                                     capture=capture, before_request=before_request)
                row.update(status='returned', result=result)
                counts['symbols_received'] += 1
                capture_state['status'] = 'completed_probe'
                atomic_json(destination / 'symbols' / f'{index:04}' / 'capture/manifest.json', capture_state)
            except DataError as exc:
                safe = exc.args[0] if len(exc.args) == 1 and exc.args[0] in ERRORS else 'TRADIER_FETCH_FAILED'
                row.update(status='failed', error_code=safe)
                counts['symbols_failed'] += 1
                atomic_json(destination / 'batch.json', state)
                if safe not in local_errors:
                    raise DataError(safe) from None
            atomic_json(destination / 'batch.json', state)
            progress.advance(index + 1, counts=counts)
        state['status'] = 'completed_with_errors' if counts['symbols_failed'] else 'completed'
        state['finished_at'] = datetime.now(timezone.utc).isoformat()
        atomic_json(destination / 'batch.json', state)
        progress.finish(counts=counts)
        if counts['symbols_failed']:
            code = 'TRADIER_BATCH_PARTIAL'
    except (Exception, KeyboardInterrupt) as exc:
        code = 'RUN_CANCELLED' if isinstance(exc, KeyboardInterrupt) else 'TRADIER_FETCH_FAILED'
        if isinstance(exc, DataError) and len(exc.args) == 1 and exc.args[0] in SAFE_ERRORS:
            code = exc.args[0]
        if state is not None:
            for row in state['rows']:
                if row['status'] == 'in_progress':
                    row.update(status='failed', error_code=code)
                    counts['symbols_failed'] += 1
            state['error_code'] = code
            try:
                atomic_json(destination / 'batch.json', state)
            except OSError:
                code = 'TRADIER_FETCH_FAILED'
    finally:
        credential = None
        if progress:
            try:
                progress.end(code, counts=counts)
            except OSError:
                code = code or 'LOG_UNAVAILABLE'
            finally:
                try:
                    progress.close()
                except OSError:
                    code = code or 'LOG_UNAVAILABLE'
    report = {'schema_version': 1, 'run_id': run_id, 'code_revision': revision,
              'profile': args.profile, 'checks': [{'name': 'tradier_master_fetch',
              'status': 'failed' if code else 'passed'}], 'counts': counts, 'error_code': code}
    review = root / 'artifacts/agent-review' / f'{run_id}.json'
    try:
        atomic_json(review, report)
    except OSError:
        print('TRADIER_FETCH_FAILED: could not write sanitized review report.')
        return 1
    if destination is not None:
        print(f'User data: {destination / "batch.json"}')
    print(f'{counts["symbols_received"]}/{counts["master_symbols"]} master symbols received; {counts["symbols_failed"]} failed. Quote freshness remains unverified.')
    print(f'Agent review: {review}')
    return 130 if code == 'RUN_CANCELLED' else 1 if code else 0
