"""Thin user-run recovery commands over shared catalog services."""
from pathlib import Path

from .core import DataError
from .dashboard import atomic_json
from .progress import RunProgress
from .recovery import RecoveryService, ERRORS
from .run_ids import new_run_id
from .scan_service import code_revision


def add_commands(subs):
    backup = subs.add_parser('catalog-backup', help='USER-RUN: back up catalog to a new private directory')
    backup.add_argument('--destination', type=Path, required=True)
    verify = subs.add_parser('catalog-backup-verify', help='USER-RUN: verify a catalog backup')
    restore = subs.add_parser('catalog-restore', help='USER-RUN: restore catalog into a new workspace')
    for command in (verify,restore):
        command.add_argument('--backup',type=Path,required=True)
    restore.add_argument('--destination',type=Path,required=True)
    for command in (backup,verify,restore):
        command.add_argument('--demo',action='store_true',help='Use the separate web demo workspace')


def run_recovery(root,args):
    if args.demo:
        root = root/'artifacts/web-demo-workspace'
    progress, code, counts = None, None, {}
    try:
        progress = RunProgress(root/'artifacts/logs',new_run_id(),args.command,'unknown',code_revision())
        progress.begin()
        service = RecoveryService(root)
        # Explicit paths are relative to the invoking workspace, even for --demo.
        if args.command == 'catalog-backup':
            counts = service.backup(args.destination,progress=progress)
        elif args.command == 'catalog-restore':
            counts = service.restore(args.backup,args.destination,progress=progress)
        else:
            manifest = service.verify(args.backup,progress=progress)
            counts = {'files':len(manifest['files']), 'bytes':manifest['database']['size']+sum(f['size'] for f in manifest['files'])}
        progress.pause()
        if args.command == 'catalog-backup':
            print(f'Catalog backup: {args.destination.absolute()}')
        elif args.command == 'catalog-restore':
            print(f'Restored catalog workspace: {args.destination.absolute()}')
        else:
            print('Catalog backup verified.')
    except (Exception,KeyboardInterrupt) as exc:
        code = ('RUN_CANCELLED' if isinstance(exc,KeyboardInterrupt) else
                exc.args[0] if isinstance(exc,DataError) and len(exc.args)==1 and exc.args[0] in ERRORS else 'RECOVERY_FAILED')
        if progress:
            progress.pause()
        print(f'{code}: recovery stopped; retain incomplete output for local review.')
    finally:
        if progress:
            try:
                if code and progress.last_counts:
                    counts = progress.last_counts
                progress.end(code,counts=counts)
                path = root/'artifacts/agent-review'/f'{progress.run_id}.json'
                atomic_json(path,{'schema_version':1,'run_id':progress.run_id,'code_revision':code_revision(),
                                 'profile':'unknown','checks':[{'name':'catalog_recovery','status':'failed' if code else 'passed'}],
                                 'counts':counts,'error_code':code})
                print(f'Agent review: {path}')
            except OSError:
                code = 'LOG_UNAVAILABLE'
            finally:
                progress.close()
    return 130 if code == 'RUN_CANCELLED' else 1 if code else 0
