"""Explicit local report composition and user-run daily orchestration."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import uuid

from .core import DataError, calculate, normalize_universe
from .dashboard import (combine, read_json, ota_checked, history_previous,
                        save_history, write_dashboard, synthetic_ota, atomic_json, FILTER_DEFAULTS)
from .demo import make_snapshot
from .progress import RunProgress, SAFE_ERRORS
from .report import write_csv


def newest(paths):
    paths = list(paths)
    if not paths:
        raise DataError('DASHBOARD_INPUT_MISSING')
    return max(paths, key=lambda p: (p.stat().st_mtime_ns, str(p)))


def run_dashboard(root, args):
    from .cli import code_revision
    run_id, progress = uuid.uuid4().hex, None
    profile, counts, code = 'synthetic' if args.command == 'dashboard-demo' else 'public', {}, None
    try:
        progress = RunProgress(root / 'artifacts' / 'logs', run_id, args.command, profile, code_revision())
        progress.begin()
        progress.start('snapshot_load')
        demo = args.command == 'dashboard-demo'
        if demo:
            snapshot = make_snapshot()
            ota = synthetic_ota(snapshot)
            now = datetime.fromisoformat(ota['retrieved_at'])
        else:
            snapshot_path = args.snapshot or newest(root.glob('artifacts/runs/public/*/snapshot.json'))
            ota_path = args.ota or newest([*root.glob('artifacts/ota/*/results.json'), *root.glob('artifacts/ota/*/page.json')])
            snapshot, ota = read_json(snapshot_path), read_json(ota_path)
            now = datetime.now(timezone.utc)
            if snapshot.get('profile') != 'public':
                raise DataError('DASHBOARD_INPUT_INVALID')
        progress.finish()
        progress.start('dashboard')
        config_path = getattr(args, 'filters', None) or root / 'config' / 'candidates.json'
        if getattr(args, 'filters', None) and not config_path.exists():
            raise DataError('CANDIDATE_CONFIG_INVALID')
        filters = read_json(config_path) if config_path.exists() else FILTER_DEFAULTS
        history_dir = root / 'artifacts' / 'history' / profile
        previous = history_previous(history_dir, snapshot)
        if demo and previous is None:
            old = deepcopy(snapshot)
            old['sessions'] = old['sessions'][:-1]
            old['as_of'] = old['sessions'][-1]
            save_history(history_dir, calculate(old))
            previous = history_previous(history_dir, snapshot)
        result = combine(snapshot, ota, filters, now=now, previous=previous)
        if not result['ranked']:
            raise DataError('NO_VALID_PEER_GROUP')
        counts = {'ranked': len(result['ranked']), 'excluded': len(result['excluded']),
                  'matched': sum(r['ota_status'] == 'returned' for r in result['combined']),
                  'candidates': sum(r['review_status'] == 'matches_config_unverified' for r in result['combined'])}
        progress.finish(counts=counts)
        progress.start('reports')
        destination = root / 'artifacts' / 'dashboards' / profile / run_id
        destination.mkdir(parents=True, exist_ok=False)
        atomic_json(destination / 'snapshot.json', snapshot)
        atomic_json(destination / 'ota-input.json', ota_checked(ota, profile))
        write_csv(destination / 'universe.csv', normalize_universe(snapshot['universe']), ('symbol','group','company','sector','sector_etf'))
        write_dashboard(result, destination)
        save_history(history_dir, result)
        progress.finish()
        print(f'Dashboard: {destination / "dashboard.html"}')
        print(f'{counts["ranked"]} ranked; {counts["matched"]} fresh OTA matches; {counts["candidates"]} tail rows match settings (unverified metrics).')
    except (Exception, KeyboardInterrupt) as exc:
        code = 'RUN_CANCELLED' if isinstance(exc, KeyboardInterrupt) else 'DASHBOARD_FAILED'
        if isinstance(exc, DataError) and len(exc.args) == 1 and exc.args[0] in SAFE_ERRORS:
            code = exc.args[0]
        print(f'{code}: dashboard stopped; no raw input or exception text logged.')
    if progress:
        try:
            progress.end(code, counts=counts)
            progress.close()
        except OSError:
            code = code or 'LOG_UNAVAILABLE'
    try:
        report = {'schema_version':1, 'run_id':run_id, 'code_revision':code_revision(), 'profile':profile,
                  'checks':[{'name':'combined_dashboard', 'status':'failed' if code else 'passed'}],
                  'counts':counts, 'error_code':code}
        path = root / 'artifacts' / 'agent-review' / f'{run_id}.json'
        atomic_json(path, report)
        print(f'Agent review: {path}')
    except OSError:
        code = code or 'DASHBOARD_FAILED'
    return 130 if code == 'RUN_CANCELLED' else 1 if code else 0


def run_daily(root, args):
    """Each stage has its own standard logs; never reuse old output after failure."""
    from .cli import main
    from .ota_fetch import run_fetch
    from argparse import Namespace
    before_prices = set(root.glob('artifacts/runs/public/*/snapshot.json'))
    before_ota = set(root.glob('artifacts/ota/*/results.json'))
    if main(['refresh', '--profile', 'public'], root):
        return 1
    prices = set(root.glob('artifacts/runs/public/*/snapshot.json')) - before_prices
    if run_fetch(root, page_size=args.page_size, max_pages=args.max_pages, use_stored_token=args.use_stored_token):
        return 1
    ota = set(root.glob('artifacts/ota/*/results.json')) - before_ota
    if len(prices) != 1 or len(ota) != 1:
        print('DASHBOARD_INPUT_MISSING: daily stage output missing or ambiguous.')
        return 1
    return run_dashboard(root, Namespace(command='dashboard', snapshot=prices.pop(), ota=ota.pop(), filters=args.filters))
