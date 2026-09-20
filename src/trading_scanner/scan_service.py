"""Shared synchronous scan application service for CLI, schedules and future web jobs."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import sys
from .run_ids import new_run_id, valid_run_id

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


def code_revision() -> str:
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.rglob("*")):
        if not path.is_file() or path.suffix not in (".py", ".html", ".css", ".sql"):
            continue
        digest.update(path.relative_to(Path(__file__).parent).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def review_summary(run_id: str, profile: str, success: bool, ranked: int, excluded: int,
                   error_code: str = "SCAN_FAILED") -> dict:
    # This allowlist excludes provider bodies, symbols, holdings, identities,
    # headers and exception text. It is the only artifact agents should inspect
    # after a public run; market-data snapshots/reports are for the user.
    if profile not in {"synthetic", "public"} or not valid_run_id(run_id):
        raise DataError("INVALID_REPORT_METADATA")
    if type(ranked) is not int or type(excluded) is not int or min(ranked, excluded) < 0:
        raise DataError("INVALID_REPORT_COUNTS")
    if error_code not in SAFE_ERRORS:
        error_code = "SCAN_FAILED"
    return {"schema_version": 1, "run_id": run_id, "code_revision": code_revision(),
            "profile": profile, "checks": [{"name": "momentum_scan", "status": "passed" if success else "failed"}],
            "counts": {"ranked": ranked, "excluded": excluded},
            "error_code": None if success else error_code}


def run_scan(args, root):
    if args.command not in ("demo", "cached", "refresh"):
        raise DataError("SCAN_FAILED")
    run_id = new_run_id()
    profile = "public" if args.command != "demo" else "synthetic"
    artifact_root = root / "artifacts"
    review = artifact_root / "agent-review"
    ranked = excluded = 0
    progress = None
    try:
        progress = RunProgress(artifact_root / "logs", run_id, args.command,
                               "unknown" if args.command == "cached" else profile, code_revision())
        progress.begin()
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
