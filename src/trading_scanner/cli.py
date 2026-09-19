"""Offline defaults and explicit user-run public refresh."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sys
import uuid

from .core import calculate, DataError, normalize_universe
from .demo import make_snapshot
from .report import write_reports, write_csv
from .progress import RunProgress, SAFE_ERRORS
from .options_data import enrich, synthetic_options, validate_options


class DiscardOutput:
    """Do not capture raw provider output, even temporarily in a log file."""
    def write(self, text):
        return len(text)

    def flush(self):
        pass


class OfflineArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        # Fixed-width, plain help does not consult terminal environment settings.
        kwargs.setdefault("formatter_class", lambda prog: argparse.HelpFormatter(prog, width=88))
        if sys.version_info >= (3, 14):
            kwargs.setdefault("color", False)
        super().__init__(*args, **kwargs)


def code_revision() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def review_summary(run_id: str, profile: str, success: bool, ranked: int, excluded: int,
                   error_code: str = "SCAN_FAILED") -> dict:
    # This allowlist excludes provider bodies, symbols, holdings, identities,
    # headers and exception text. It is the only artifact agents should inspect
    # after a public run; market-data snapshots/reports are for the user.
    if profile not in {"synthetic", "public"} or len(run_id) != 32 or any(c not in "0123456789abcdef" for c in run_id):
        raise DataError("INVALID_REPORT_METADATA")
    if type(ranked) is not int or type(excluded) is not int or min(ranked, excluded) < 0:
        raise DataError("INVALID_REPORT_COUNTS")
    if error_code not in SAFE_ERRORS:
        error_code = "SCAN_FAILED"
    return {"schema_version": 1, "run_id": run_id, "code_revision": code_revision(),
            "profile": profile, "checks": [{"name": "momentum_scan", "status": "passed" if success else "failed"}],
            "counts": {"ranked": ranked, "excluded": excluded},
            "error_code": None if success else error_code}


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
    ota_fetch.add_argument('--max-pages', type=int, choices=range(1, 101), default=50, metavar='1..100')
    ota_fetch.add_argument('--use-stored-token', action='store_true', help='USER-RUN: read the token from the OS credential store')
    subs.add_parser('dashboard-demo', help='Create a synthetic combined dashboard with prior-session history')
    dashboard = subs.add_parser('dashboard', help='USER-RUN: join cached prices and OTA; defaults to latest successful files')
    dashboard.add_argument('--snapshot', type=Path)
    dashboard.add_argument('--ota', type=Path)
    dashboard.add_argument('--filters', type=Path)
    dashboard.add_argument('--tradier', type=Path, action='append', default=[],
                           help='Attach a saved atm-spreads.json; repeat for distinct symbols, one profile only')
    daily = subs.add_parser('daily', help='USER-RUN: refresh public prices, fetch OTA, write combined dashboard')
    daily.add_argument('--profile', choices=['public'], required=True)
    daily.add_argument('--page-size', type=int, choices=range(1,601), default=100, metavar='1..600', help='Rows per OTA page (default: 100)')
    daily.add_argument('--max-pages', type=int, choices=range(1,101), default=50, metavar='1..100')
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
    process = subs.add_parser('ota-process', help='USER-RUN: profile/reprocess saved raw OTA data without network')
    process.add_argument('--input', type=Path, required=True)
    args = parser.parse_args(argv)
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
        return run_fetch(root, page_size=args.page_size, max_pages=args.max_pages, use_stored_token=args.use_stored_token)
    if args.command == "ota-config":
        return configure_ota(args, root)
    run_id = uuid.uuid4().hex
    profile = "public" if args.command != "demo" else "synthetic"
    artifact_root = root / "artifacts"
    review = artifact_root / "agent-review"
    ranked = excluded = 0
    progress = None
    try:
        progress = RunProgress(artifact_root / "logs", run_id, args.command,
                               "unknown" if args.command == "cached" else profile, code_revision())
        progress.begin()
        print(f"Run log: {progress.path}", flush=True)
        if args.command == "demo":
            progress.start("synthetic_data")
            snapshot = make_snapshot()
            progress.finish()
        elif args.command == "cached":
            progress.start("snapshot_load")
            snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
            if not isinstance(snapshot, dict):
                raise DataError("INVALID_SNAPSHOT")
            profile = snapshot.get("profile")
            if not isinstance(profile, str) or profile not in {"synthetic", "public"}:
                profile = "public"
                raise DataError("INVALID_SNAPSHOT")
            progress.set_profile(profile)
            progress.finish()
        else:
            old_disable = logging.root.manager.disable
            try:
                # Includes lazy dependency imports, which may emit diagnostics.
                logging.disable(logging.CRITICAL)
                with redirect_stdout(DiscardOutput()), redirect_stderr(DiscardOutput()):
                    from .public_data import fetch_snapshot
                    snapshot = fetch_snapshot(root / "config" / "etfs.csv", progress=progress)
            finally:
                logging.disable(old_disable)
        progress.start("ranking")
        result = calculate(snapshot)
        ranked, excluded = len(result["ranked"]), len(result["excluded"])
        if ranked == 0:
            raise DataError("NO_VALID_PEER_GROUP")
        progress.finish(counts={"ranked": ranked, "excluded": excluded})
        if excluded:
            progress.exclusions(excluded)
        if getattr(args, "options_file", None) or getattr(args, "with_options", False) or "options_input" in snapshot:
            progress.start("options")
            payload = snapshot.get("options_input")
            if getattr(args, "options_file", None):
                try:
                    with args.options_file.open("rb") as stream:
                        raw = stream.read(2_000_001)
                    if len(raw) > 2_000_000:
                        raise DataError("INVALID_OPTIONS_INPUT")
                    payload = json.loads(raw)
                except (OSError, ValueError):
                    raise DataError("INVALID_OPTIONS_INPUT") from None
            elif getattr(args, "with_options", False):
                payload = synthetic_options(result)
            snapshot["options_input"] = validate_options(payload, profile)
            result = enrich(result, snapshot["options_input"])
            progress.finish()
        progress.start("reports")
        destination = artifact_root / ("replay" if args.command == "cached" else "runs") / profile / run_id
        destination.mkdir(parents=True, exist_ok=False)
        snapshot_bytes = (json.dumps(snapshot, indent=2, allow_nan=False) + "\n").encode("utf-8")
        (destination / "snapshot.json").write_bytes(snapshot_bytes)
        result.update(snapshot_sha256=hashlib.sha256(snapshot_bytes).hexdigest(),
                      generated_at=datetime.now(timezone.utc).isoformat(), command=args.command,
                      code_revision=code_revision())
        write_csv(destination / "universe.csv", normalize_universe(snapshot["universe"]),
                  ("symbol", "group", "company", "sector", "sector_etf"))
        write_reports(result, destination)
        progress.finish()
        progress.start("summary")
        review.mkdir(parents=True, exist_ok=True)
        summary = review_summary(run_id, profile, True, ranked, excluded)
        (review / f"{run_id}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        progress.finish()
        progress.end(counts={"ranked": ranked, "excluded": excluded})
        print(f"{profile.upper()} | as of {result['as_of']} | {ranked} ranked | {excluded} excluded")
        print(f"Report: {destination / 'report.html'}")
        print(f"Snapshot: {destination / 'snapshot.json'}")
        print(f"Agent review: {review / (run_id + '.json')}")
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        error_code = "SCAN_FAILED"
        if isinstance(exc, KeyboardInterrupt):
            error_code = "RUN_CANCELLED"
        elif progress is None and isinstance(exc, OSError):
            error_code = "LOG_UNAVAILABLE"
        elif isinstance(exc, ModuleNotFoundError):
            error_code = "DEPENDENCY_UNAVAILABLE"
        elif isinstance(exc, FileNotFoundError) and args.command == "cached":
            error_code = "MISSING_SNAPSHOT"
        elif isinstance(exc, DataError) and len(exc.args) == 1 and exc.args[0] in SAFE_ERRORS:
            error_code = exc.args[0]
        if progress is not None:
            try:
                progress.end(error_code, counts={"ranked": ranked, "excluded": excluded})
            except OSError:
                print("LOG_UNAVAILABLE: unable to write final run event.")
        try:
            review.mkdir(parents=True, exist_ok=True)
            summary = review_summary(run_id, profile, False, ranked, excluded, error_code)
            (review / f"{run_id}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
            print(f"Agent review: {review / (run_id + '.json')}")
        except OSError:
            print("SUMMARY_UNAVAILABLE: unable to write review report.")
        print(f"{error_code}: check dependency setup and inputs; no synthetic fallback or raw response logged.")
        return 130 if error_code == "RUN_CANCELLED" else 1
    finally:
        if progress is not None:
            try:
                progress.close()
            except OSError:
                print("LOG_UNAVAILABLE: unable to close run log.")


def configure_ota(args, root):
    from .ota_config import parse_config, save_config, read_paste, MAX_INPUT
    progress = None
    try:
        progress = RunProgress(root / 'artifacts' / 'logs', uuid.uuid4().hex,
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
            print('Saved config/ota-screener.json. No provider request was made.')
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
