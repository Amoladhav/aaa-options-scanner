"""Explicit local report composition and user-run daily orchestration."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from .run_ids import new_run_id

from .core import DataError, normalize_universe
from .dashboard import (read_json, write_dashboard, synthetic_ota, atomic_json, FILTER_DEFAULTS)
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
    run_id, progress = new_run_id(), None
    profile, counts, code = 'synthetic' if args.command == 'dashboard-demo' else 'public', {}, None
    try:
        progress = RunProgress(root / 'artifacts' / 'logs', run_id, args.command, profile, code_revision())
        progress.begin()
        progress.start('snapshot_load')
        demo = args.command == 'dashboard-demo'
        if demo:
            snapshot = make_snapshot()
            ota = synthetic_ota(snapshot)
            members = {row['symbol']: row for row in snapshot['universe']}
            ota.update(schema_version=2, representation='ota_raw', acquisition_status='completed_short_page')
            ota['rows'] = [{'symbol': row['symbol'], 'values':{**{k:v for k,v in row.items() if k != 'symbol'},
                           'sector':members[row['symbol']].get('sector',''), 'industry':'Invented example',
                           'avgVol30d':1234567, 'last':42.12345, 'customExample':{'invented':True}}} for row in ota['rows']]
            now = datetime.fromisoformat(ota['retrieved_at'])
        else:
            snapshot_path = args.snapshot or newest(root.glob('artifacts/runs/public/*/snapshot.json'))
            ota_path = args.ota or newest([*root.glob('artifacts/ota/*/results.json'), *root.glob('artifacts/ota/*/page.json')])
            snapshot, ota = read_json(snapshot_path), read_json(ota_path, limit=220_000_000)
            now = datetime.now(timezone.utc)
            if snapshot.get('profile') != 'public':
                raise DataError('DASHBOARD_INPUT_INVALID')
        progress.finish()
        progress.start('dashboard')
        config_path = getattr(args, 'filters', None) or root / 'config' / 'candidates.json'
        if getattr(args, 'filters', None) and not config_path.exists():
            raise DataError('CANDIDATE_CONFIG_INVALID')
        filters = read_json(config_path) if config_path.exists() else FILTER_DEFAULTS
        from .catalog import Catalog
        from .crs_history import CRSHistory
        from .report_service import ReportService
        catalog = Catalog(root)
        catalog.initialize()
        service = ReportService(catalog)
        if demo and CRSHistory(catalog).prior(snapshot) is None:
            old = deepcopy(snapshot)
            old['sessions'] = old['sessions'][:-1]
            old['as_of'] = old['sessions'][-1]
            old['membership_observed_at'] = old['as_of']
            progress.pause()
            service.generate_from_payloads(old,None,now=now)
        probes = [read_json(path) for path in getattr(args, 'tradier', [])]
        progress.pause()
        artifact_id = service.generate_from_payloads(snapshot,ota,filters=filters,now=now,probes=probes)
        result = service.load(artifact_id)
        if not result['combined']:
            raise DataError('NO_VALID_PEER_GROUP')
        counts = {'ota_received': result['ota_join_counts']['received'], 'ota_outside_master':result['ota_join_counts']['outside_master'],
                  'master_symbols': len(result['combined']), 'tradier_matched': sum(r['tradier_status'] == 'supplied_freshness_unverified' for r in result['combined']),
                  'ranked': len(result['ranked']), 'excluded': len(result['excluded']),
                  'matched': sum(r['ota_status'] == 'returned' for r in result['combined']),
                  'candidates': sum(r['review_status'] == 'matches_config_unverified' for r in result['combined'])}
        progress.finish(counts=counts)
        progress.start('reports')
        destination = root / 'artifacts' / 'dashboards' / profile / run_id
        destination.mkdir(parents=True, exist_ok=False)
        atomic_json(destination / 'snapshot.json', snapshot)
        atomic_json(destination / 'ota-input.json', ota)
        write_csv(destination / 'universe.csv', normalize_universe(snapshot['universe']), ('symbol','group','company','sector','sector_etf'))
        atomic_json(destination / 'tradier-inputs.json', probes)
        write_dashboard(result, destination)
        progress.finish()
        print(f'Catalog report ID: {artifact_id}')
        print(f'Dashboard: {destination / "dashboard.html"}')
        print(f'Excel CSV (all master rows): {destination / "master.csv"}')
        print(f'Combined CSV: {destination / "combined.csv"}')
        print(f'Rankings CSV: {destination / "rankings.csv"}')
        statuses = [row['tradier_status'] for row in result['combined']]
        print(f'Tradier: input files={len(probes)}; attached={counts["tradier_matched"]}; failed={statuses.count("failed")}; not attempted={statuses.count("not_attempted")}; in progress={statuses.count("in_progress")}; not supplied={statuses.count("not_supplied")}.')
        if not probes:
            print('No Tradier file attached. Regenerate with --tradier PATH_TO_BATCH_JSON to include saved quotes.')
        print(f'OTA received: {result["ota_join_counts"]["received"]}; matched to master: {result["ota_join_counts"]["matched"]}; outside master: {result["ota_join_counts"]["outside_master"]}.')
        print(f'{counts["ranked"]} ranked; {counts["matched"]} fresh OTA matches; {counts["candidates"]} tail rows match settings (unverified metrics).')
    except (Exception, KeyboardInterrupt) as exc:
        if progress:
            progress.pause()
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
    from .scan_service import run_scan
    from .ota_fetch import run_fetch
    from argparse import Namespace
    before_prices = set(root.glob('artifacts/runs/public/*/snapshot.json'))
    before_ota = set(root.glob('artifacts/ota/*/results.json'))
    code = run_scan(Namespace(command='refresh', profile='public', options_file=None), root)
    if code:
        return code
    prices = set(root.glob('artifacts/runs/public/*/snapshot.json')) - before_prices
    code = run_fetch(root, page_size=args.page_size, max_pages=args.max_pages, use_stored_token=args.use_stored_token, credential_source=getattr(args, 'credential_source', None))
    if code:
        return code
    ota = set(root.glob('artifacts/ota/*/results.json')) - before_ota
    if len(prices) != 1 or len(ota) != 1:
        print('DASHBOARD_INPUT_MISSING: daily stage output missing or ambiguous.')
        return 1
    return run_dashboard(root, Namespace(command='dashboard', snapshot=prices.pop(), ota=ota.pop(), filters=args.filters))
