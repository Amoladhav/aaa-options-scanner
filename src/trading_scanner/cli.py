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

SAFE_ERRORS = {"SCAN_FAILED", "DEPENDENCY_UNAVAILABLE", "CONSTITUENTS_SCHEMA_CHANGED",
               "CONSTITUENTS_COUNT_INVALID", "CONSTITUENTS_RESPONSE_TOO_LARGE",
               "NO_VALID_PEER_GROUP", "INVALID_SNAPSHOT", "INSUFFICIENT_CALENDAR",
               "MISSING_SNAPSHOT", "INVALID_SESSION_ORDER", "WEEKEND_SESSION",
               "INVALID_SYMBOL", "CONFLICTING_SYMBOL", "INVALID_GROUP", "INVALID_ETF_CONFIG"}


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
    subs.add_parser("demo", help="Invented prices; no third-party dependencies or network")
    cached = subs.add_parser("cached", help="Replay a local snapshot; never refresh")
    cached.add_argument("--snapshot", type=Path, required=True)
    refresh = subs.add_parser("refresh", help="USER-RUN: download public prices and current constituents")
    refresh.add_argument("--profile", choices=["public"], required=True)
    args = parser.parse_args(argv)
    run_id = uuid.uuid4().hex
    profile = "public" if args.command != "demo" else "synthetic"
    artifact_root = root / "artifacts"
    review = artifact_root / "agent-review"
    review.mkdir(parents=True, exist_ok=True)
    ranked = excluded = 0
    try:
        if args.command == "demo":
            snapshot = make_snapshot()
        elif args.command == "cached":
            snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
            if not isinstance(snapshot, dict):
                raise DataError("INVALID_SNAPSHOT")
            profile = snapshot.get("profile")
            if not isinstance(profile, str) or profile not in {"synthetic", "public"}:
                profile = "public"
                raise DataError("INVALID_SNAPSHOT")
        else:
            old_disable = logging.root.manager.disable
            try:
                # Includes lazy dependency imports, which may emit diagnostics.
                logging.disable(logging.CRITICAL)
                with redirect_stdout(DiscardOutput()), redirect_stderr(DiscardOutput()):
                    from .public_data import fetch_snapshot
                    snapshot = fetch_snapshot(root / "config" / "etfs.csv")
            finally:
                logging.disable(old_disable)
        result = calculate(snapshot)
        ranked, excluded = len(result["ranked"]), len(result["excluded"])
        if ranked == 0:
            raise DataError("NO_VALID_PEER_GROUP")
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
        summary = review_summary(run_id, profile, True, ranked, excluded)
        (review / f"{run_id}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"{profile.upper()} | as of {result['as_of']} | {ranked} ranked | {excluded} excluded")
        print(f"Report: {destination / 'report.html'}")
        print(f"Snapshot: {destination / 'snapshot.json'}")
        print(f"Agent review: {review / (run_id + '.json')}")
        return 0
    except Exception as exc:
        error_code = "SCAN_FAILED"
        if isinstance(exc, ModuleNotFoundError):
            error_code = "DEPENDENCY_UNAVAILABLE"
        elif isinstance(exc, FileNotFoundError) and args.command == "cached":
            error_code = "MISSING_SNAPSHOT"
        elif isinstance(exc, DataError) and len(exc.args) == 1 and exc.args[0] in SAFE_ERRORS:
            error_code = exc.args[0]
        summary = review_summary(run_id, profile, False, ranked, excluded, error_code)
        (review / f"{run_id}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(f"{error_code}: check dependency setup and inputs; no synthetic fallback or raw response logged.")
        print(f"Agent review: {review / (run_id + '.json')}")
        return 1
