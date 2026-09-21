"""Thin user-run history commands; only explicit catalog IDs, never fetches."""
import json

from .catalog import Catalog
from .core import DataError
from .crs_history import CRSHistory
from .dashboard import atomic_json
from .progress import RunProgress
from .report_service import ReportService
from .run_ids import new_run_id
from .scan_service import code_revision
from .legacy_history import LegacyHistory


def add_commands(subs):
    listing = subs.add_parser('history-list', help='USER-RUN: list recorded CRS report revisions')
    listing.add_argument('--profile', choices=('synthetic', 'public'), required=True)
    listing.add_argument('--limit', type=int, default=100)
    show = subs.add_parser('history-show', help='USER-RUN: inspect one recorded CRS report')
    show.add_argument('--report', required=True)
    compare = subs.add_parser('history-compare', help='USER-RUN: compare two explicit CRS report revisions')
    compare.add_argument('--left', required=True)
    compare.add_argument('--right', required=True)
    replay = subs.add_parser('report-replay', help='USER-RUN: replay exact saved inputs and evaluation time with the same code')
    replay.add_argument('--report', required=True)
    build = subs.add_parser('report-build', help='USER-RUN: build a saved report from catalog source IDs without fetching')
    build.add_argument('--prices', required=True)
    build.add_argument('--ota')
    build.add_argument('--tradier')
    preview = subs.add_parser('history-preview', help='USER-RUN: preview legacy daily history without importing')
    apply = subs.add_parser('history-import', help='USER-RUN: import a reviewed legacy preview')
    apply.add_argument('--preview-id', required=True)
    batches = subs.add_parser('history-imports', help='USER-RUN: list legacy import batches')
    rollback = subs.add_parser('history-rollback', help='USER-RUN: deactivate one legacy import batch, retaining evidence')
    rollback.add_argument('--batch',required=True)
    for command in (preview,apply,batches):
        command.add_argument('--profile',choices=('synthetic','public'),required=True)
    for command in (preview,apply):
        command.add_argument('--session',help='Optional single YYYY-MM-DD legacy file')
    for command in (listing, show, compare, replay, build, preview, apply, batches, rollback):
        command.add_argument('--demo', action='store_true', help='Use the separate web demo workspace')


def run_history(root, args):
    if args.demo:
        root = root/'artifacts/web-demo-workspace'
    progress = None
    counts, code = {}, None
    try:
        progress = RunProgress(root/'artifacts/logs', new_run_id(), args.command, 'unknown', code_revision())
        progress.begin(); progress.start('catalog')
        catalog = Catalog(root)
        if args.command not in ('history-preview','history-import'):
            catalog.initialize()
        history = CRSHistory(catalog)
        legacy = LegacyHistory(catalog)
        if args.command == 'history-preview':
            output=legacy.preview(args.profile,args.session)
            counts={'rows':len(output['entries'])}
        elif args.command == 'history-import':
            output=legacy.apply(args.profile,args.preview_id,args.session)
            counts={'indexed':output['imported']}
        elif args.command == 'history-imports':
            output=legacy.batches(args.profile)
            counts={'rows':len(output)}
        elif args.command == 'history-rollback':
            output=legacy.rollback(args.batch)
            counts={'changed':output['deactivated']}
        elif args.command == 'history-list':
            output = history.list(args.profile, limit=args.limit)
            counts = {'rows': len(output)}
        elif args.command == 'history-show':
            output = history.show(args.report)
            counts = {'rows': len(output['rows'])}
        elif args.command == 'history-compare':
            output = history.compare(args.left, args.right)
            counts = {'rows': len(output['changes'])}
        elif args.command == 'report-replay':
            output = {'artifact_id': ReportService(catalog).replay(args.report)}
        elif args.command == 'report-build':
            output = {'artifact_id': ReportService(catalog).generate(args.prices,args.ota,args.tradier)}
        else:
            raise DataError('HISTORY_INVALID')
        progress.finish(counts=counts)
        # Explicit user-facing output, never copied into logs/review reports.
        print(json.dumps(output, indent=2, ensure_ascii=True, allow_nan=False))
    except (Exception, KeyboardInterrupt) as exc:
        safe = {'HISTORY_NOT_RECORDED','HISTORY_REPLAY_VERSION_MISMATCH',
                'HISTORY_COMPARISON_INCOMPATIBLE','HISTORY_INVALID','HISTORY_PREVIEW_STALE',
                'HISTORY_IMPORT_BLOCKED','HISTORY_IMPORT_LIMIT','HISTORY_UPGRADE_REQUIRED','HISTORY_IMPORT_NOT_FOUND'}
        code = ('RUN_CANCELLED' if isinstance(exc, KeyboardInterrupt) else
                exc.args[0] if isinstance(exc, DataError) and len(exc.args)==1 and exc.args[0] in safe else 'HISTORY_FAILED')
        print(f'{code}: check selected report IDs, software revision and catalog availability.')
    finally:
        if progress:
            try:
                progress.end(code, counts=counts)
                path = root/'artifacts/agent-review'/f'{progress.run_id}.json'
                atomic_json(path, {'schema_version':1,'run_id':progress.run_id,'code_revision':code_revision(),
                                   'profile':'unknown','checks':[{'name':'history','status':'failed' if code else 'passed'}],
                                   'counts':counts,'error_code':code})
                print(f'Agent review: {path}')
            except OSError:
                code = 'LOG_UNAVAILABLE'
            finally:
                progress.close()
    return 130 if code == 'RUN_CANCELLED' else 1 if code else 0
