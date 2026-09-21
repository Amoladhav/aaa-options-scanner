"""Offline defaults and explicit user-run public refresh."""
import argparse
import json
from pathlib import Path
import sys
from .run_ids import new_run_id

from .core import DataError
from .progress import RunProgress, SAFE_ERRORS


from .scan_service import run_scan, code_revision, review_summary


class OfflineArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        # Fixed-width, plain help does not consult terminal environment settings.
        kwargs.setdefault("formatter_class", lambda prog: argparse.HelpFormatter(prog, width=88))
        if sys.version_info >= (3, 14):
            kwargs.setdefault("color", False)
        super().__init__(*args, **kwargs)


def main(argv=None, root: Path | None = None) -> int:
    root = root or Path(__file__).resolve().parents[2]
    parser = OfflineArgumentParser(description="Cross-sectional momentum: offline demo, cached replay, or explicit public refresh.")
    subs = parser.add_subparsers(dest="command", required=True)
    demo = subs.add_parser("demo", help="Invented prices; no third-party dependencies or network")
    demo.add_argument("--with-options", action="store_true", help="Include explicitly synthetic options metrics")
    cached = subs.add_parser("cached", help="Replay a local snapshot; never refresh")
    cached.add_argument("--snapshot", type=Path, required=True)
    refresh = subs.add_parser("refresh", help="USER-RUN: download public prices and current constituents")
    refresh.add_argument("--profile", choices=["public"], required=True)
    for command in (cached, refresh):
        command.add_argument("--options-file", type=Path, help="Normalized local options JSON; no provider request")
    config = subs.add_parser("ota-config", help="Paste screener criteria to preview or save local configuration; offline",
                            description='Paste a complete OTA criteria array and press Enter. Multiline arrays are accepted; no EOF is needed. Omit --apply to preview only.',
                            epilog='Example to paste: [{"field":"optionable","valueFilter":"BOOLEAN","valueChoices":"Yes","criteria":"true"}]\nRun: python3 -I -S run.py ota-config --apply\nPaste criteria only, never headers or tokens. Abbreviated (...) entries are rejected.')
    config.add_argument("--input", type=Path, help="Read a criteria-only text file instead of stdin")
    config.formatter_class = lambda prog: argparse.RawDescriptionHelpFormatter(prog, width=88)
    config.add_argument("--apply", action="store_true", help="Replace config/ota-screener.json with validated criteria")
    ota_fetch = subs.add_parser('ota-fetch', help='USER-RUN: fetch OTA pages with a hidden token prompt')
    ota_fetch.add_argument('--profile', choices=['ota'], required=True)
    ota_fetch.add_argument('--page-size', type=int, choices=range(1, 601), default=100, metavar='1..600', help='Rows per OTA page (default: 100)')
    ota_fetch.add_argument('--max-pages', type=int, choices=range(1, 101), default=100, metavar='1..100', help='Safety ceiling, not expected page count (default: 100); stops on a short page')
    ota_fetch.add_argument('--use-stored-token', action='store_true', help='USER-RUN: read the token from the OS credential store')
    subs.add_parser('dashboard-demo', help='Create a synthetic combined dashboard with prior-session history')
    dashboard = subs.add_parser('dashboard', help='USER-RUN: join cached prices and OTA; defaults to latest successful files')
    dashboard.add_argument('--snapshot', type=Path)
    dashboard.add_argument('--ota', type=Path)
    dashboard.add_argument('--filters', type=Path)
    dashboard.add_argument('--tradier', type=Path, action='append', default=[],
                           help='Attach saved atm-spreads.json or master-driven batch.json; one profile only')
    daily = subs.add_parser('daily', help='USER-RUN: refresh public prices, fetch OTA, write combined dashboard')
    daily.add_argument('--profile', choices=['public'], required=True)
    daily.add_argument('--page-size', type=int, choices=range(1,601), default=100, metavar='1..600', help='Rows per OTA page (default: 100)')
    daily.add_argument('--max-pages', type=int, choices=range(1,101), default=100, metavar='1..100', help='Safety ceiling, not expected page count (default: 100); stops on a short page')
    daily.add_argument('--use-stored-token', action='store_true')
    daily.add_argument('--filters', type=Path)
    token = subs.add_parser('ota-token', help='USER-RUN: set or delete the session token in the OS credential store')
    token.add_argument('action', choices=['set','delete'])
    tradier_token = subs.add_parser('tradier-token', help='USER-RUN: store/delete a Tradier key in the OS credential store')
    tradier_token.add_argument('action', choices=['set','delete'])
    tradier_token.add_argument('--profile', choices=['sandbox','production'], required=True)
    probe = subs.add_parser('tradier-probe', help='USER-RUN: standalone monthly ATM spread probe; no dashboard integration')
    probe.add_argument('--profile', choices=['sandbox','production'], required=True)
    probe.add_argument('--symbol', required=True)
    probe.add_argument('--prompt-token', action='store_true', help='Hidden key input for this run only; bypass OS storage')
    probe.add_argument('--as-of', help='Explicit New York date YYYY-MM-DD; otherwise uses America/New_York timezone data')
    batch = subs.add_parser('tradier-fetch', help='USER-RUN: fetch ATM data for every master-universe symbol')
    batch.add_argument('--profile', choices=['sandbox', 'production'], required=True)
    batch.add_argument('--snapshot', type=Path, help='Public price snapshot containing master universe; defaults to latest saved')
    batch.add_argument('--prompt-token', action='store_true', help='Hidden key input once for the entire batch')
    batch.add_argument('--as-of', help='Explicit New York date YYYY-MM-DD')
    process = subs.add_parser('ota-process', help='USER-RUN: profile/reprocess saved raw OTA data without network')
    process.add_argument('--input', type=Path, required=True)
    ota_report = subs.add_parser('ota-report', help='USER-RUN: console, HTML, CSV and JSON report from a saved OTA fetch; no network')
    ota_report.add_argument('--input', type=Path, help='Completed raw results.json; defaults to latest saved OTA results, never in-progress capture')
    ota_demo = subs.add_parser('ota-report-demo', help='Offline OTA report preview with invented data')
    for command in (ota_report, ota_demo):
        command.add_argument('--console-rows', type=int, choices=range(101), default=20, metavar='0..100')
        command.add_argument('--page-size', type=int, choices=(25,50,100,250), default=100, help='Initial HTML rows per page; all exports retain all rows')
    for command in (ota_fetch, daily, probe, batch):
        # Keep legacy flags but reject ambiguous source selection before any I/O.
        command.add_argument('--credential-source', choices=('env', 'store', 'prompt', 'auto'))
    check = subs.add_parser('credential-check', help='USER-RUN: local format check only; no provider request')
    check.add_argument('--provider', choices=('ota', 'tradier'), required=True)
    check.add_argument('--profile', choices=('ota', 'sandbox', 'production'), required=True)
    check.add_argument('--credential-source', choices=('env', 'store'), required=True)
    web = subs.add_parser('web', help='Explicit localhost saved-results preview; no provider calls')
    web.add_argument('--demo', action='store_true', help='Use a separate invented-data workspace')
    web.add_argument('--port', type=int, default=8765)
    subs.add_parser('catalog-init', help='Initialize local metadata only; never activate scheduling')
    subs.add_parser('catalog-reconcile', help='USER-RUN: check registered files and orphan counts')
    index = subs.add_parser('catalog-index', help='USER-RUN: index one saved source; no provider requests')
    index.add_argument('--kind', choices=('prices','ota','tradier'), required=True)
    index.add_argument('--input', type=Path, required=True)
    from .schedule_cli import add_commands, run_schedule
    add_commands(subs)
    from .history_cli import add_commands as add_history_commands
    add_history_commands(subs)
    from .recovery_cli import add_commands as add_recovery_commands
    add_recovery_commands(subs)
    from .credential_setup import add_commands as add_setup_commands
    add_setup_commands(subs)
    args = parser.parse_args(argv)
    if getattr(args, 'credential_source', None) and (getattr(args, 'use_stored_token', False) or getattr(args, 'prompt_token', False)):
        parser.error('Choose --credential-source or the legacy credential flag, not both.')
    if args.command == 'web':
        from .web_cli import run_web
        return run_web(root, args)
    if args.command.startswith('history-') or args.command in ('report-build','report-replay'):
        from .history_cli import run_history
        return run_history(root,args)
    if args.command in ('catalog-backup','catalog-backup-verify','catalog-restore'):
        from .recovery_cli import run_recovery
        return run_recovery(root,args)
    if args.command.startswith('catalog-'):
        from .catalog_service import run_catalog
        return run_catalog(root, args)
    if args.command == 'credential-manage':
        from .credential_setup import run_setup
        return run_setup(root,args)
    if args.command == 'credential-check':
        from .credentials import run_check
        return run_check(root, args)
    if args.command in ('ota-report', 'ota-report-demo'):
        from .ota_report_service import generate_report
        from .ota_reporting import ReportOptions
        return generate_report(root, source=getattr(args,'input',None), options=ReportOptions(args.console_rows,args.page_size), demo=args.command=='ota-report-demo')
    if args.command in ('schedule', 'schedule-worker'):
        return run_schedule(root, args)
    if args.command == 'tradier-fetch':
        from .tradier_batch import run_batch
        return run_batch(root, args)
    if args.command == 'ota-process':
        from .ota_pipeline import run_process
        return run_process(root, args)
    if args.command == 'tradier-token':
        from .token_store import run_store
        return run_store(root, args.action, provider='tradier', profile=args.profile)
    if args.command == 'tradier-probe':
        from .tradier import run_probe
        return run_probe(root, args)

    if args.command == 'ota-token':
        from .token_store import run_store
        return run_store(root, args.action)
    if args.command in ('dashboard', 'dashboard-demo'):
        from .workflow import run_dashboard
        return run_dashboard(root, args)
    if args.command == 'daily':
        from .workflow import run_daily
        return run_daily(root, args)
    if args.command == 'ota-fetch':
        from .ota_fetch import run_fetch
        return run_fetch(root, page_size=args.page_size, max_pages=args.max_pages, use_stored_token=args.use_stored_token, credential_source=args.credential_source)
    if args.command == "ota-config":
        return configure_ota(args, root)
    return run_scan(args, root)


def configure_ota(args, root):
    from .ota_config import parse_config, save_config, read_paste, MAX_INPUT, config_identity
    progress = None
    try:
        progress = RunProgress(root / 'artifacts' / 'logs', new_run_id(),
                               'ota-config', 'unknown', code_revision())
        progress.begin()
        progress.start('config_parse')
        if args.input:
            with args.input.open(encoding='utf-8') as stream:
                pasted = stream.read(MAX_INPUT + 1)
        else:
            print('Paste the complete criteria array, then press Enter. Multiline paste works; no EOF needed.', flush=True)
            print('Example: [{"field":"optionable","valueFilter":"BOOLEAN","valueChoices":"Yes","criteria":"true"}]', flush=True)
            pasted = read_paste(sys.stdin)
        config = parse_config(pasted)
        progress.finish()
        print(json.dumps(config, indent=2, allow_nan=False))
        if args.apply:
            progress.start('config_save')
            save_config(config, root / 'config' / 'ota-screener.json')
            progress.finish()
            print(f"Saved config: {(root / 'config/ota-screener.json').resolve()}")
            print(f"Criteria SHA256: {config_identity(config)['criteria_sha256']}")
            print('No provider request was made.')
        else:
            print('Preview only. Use --apply to replace config/ota-screener.json.')
        progress.end()
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        code = 'RUN_CANCELLED' if isinstance(exc, KeyboardInterrupt) else 'OTA_CONFIG_INVALID'
        if isinstance(exc, DataError) and len(exc.args) == 1 and exc.args[0] in SAFE_ERRORS:
            code = exc.args[0]
        if progress:
            try:
                progress.end(code)
            except OSError:
                pass
        print(f'{code}: use a complete criteria array; no raw input or exception details logged.')
        return 130 if code == 'RUN_CANCELLED' else 1
    finally:
        if progress:
            try:
                progress.close()
            except OSError:
                print('LOG_UNAVAILABLE: unable to close run log.')
