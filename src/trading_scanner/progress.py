"""Shared stdout progress and structured, allowlisted run events.

Write directly to the original stdout stream so application progress remains
visible while noisy provider stdout/stderr and logging are suppressed. No raw
log message, exception, provider identifier, or arbitrary metadata is accepted.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from time import monotonic

SAFE_ERRORS = {"SCAN_FAILED", "DEPENDENCY_UNAVAILABLE", "CONSTITUENTS_SCHEMA_CHANGED",
               "CONSTITUENTS_COUNT_INVALID", "CONSTITUENTS_RESPONSE_TOO_LARGE",
               "NO_VALID_PEER_GROUP", "INVALID_SNAPSHOT", "INSUFFICIENT_CALENDAR",
               "MISSING_SNAPSHOT", "INVALID_SESSION_ORDER", "WEEKEND_SESSION",
               "INVALID_SYMBOL", "CONFLICTING_SYMBOL", "INVALID_GROUP", "INVALID_ETF_CONFIG",
               "LOG_UNAVAILABLE", "RUN_CANCELLED", "INVALID_OPTIONS_INPUT",
               "OTA_CONFIG_INVALID", "OTA_CONFIG_TOO_LARGE", "OTA_CONFIG_INCOMPLETE",
               "OTA_CONFIG_SYNTAX", "OTA_CONFIG_UNSUPPORTED_FILTER", "OTA_CONFIG_RANGE_REVERSED",
               "OTA_TOKEN_INVALID", "OTA_PROMPT_UNAVAILABLE", "OTA_AUTH_REJECTED", "OTA_RATE_LIMITED",
               "OTA_REDIRECT_REJECTED", "OTA_HTTP_ERROR", "OTA_NETWORK_ERROR", "OTA_RESPONSE_TOO_LARGE",
               "OTA_PROCESS_INVALID", "OTA_SCHEMA_INVALID", "OTA_ENVELOPE_UNSUPPORTED", "OTA_FETCH_FAILED",
               "OTA_PAGINATION_INVALID", "OTA_DUPLICATE_PAGE_SYMBOL", "OTA_PAGE_LIMIT",
               "DASHBOARD_INPUT_INVALID", "DASHBOARD_INPUT_MISSING", "DASHBOARD_FAILED",
               "HISTORY_INVALID", "CANDIDATE_CONFIG_INVALID", "TOKEN_STORE_UNAVAILABLE", "TOKEN_STORE_EMPTY",
               "TRADIER_INVALID_INPUT", "TRADIER_TOKEN_INVALID", "TRADIER_AUTH_REJECTED",
               "TRADIER_RATE_LIMITED", "TRADIER_REDIRECT_REJECTED", "TRADIER_HTTP_ERROR",
               "TRADIER_NETWORK_ERROR", "TRADIER_RESPONSE_TOO_LARGE", "TRADIER_SCHEMA_INVALID",
               "TRADIER_MONTHLY_UNVERIFIED", "TRADIER_NO_ATM_PAIR", "TRADIER_FETCH_FAILED"}
STAGES = {
    "ota_profile": "Profiling captured fields and preparing typed data",
    "run": "Scanner",
    "synthetic_data": "Generating synthetic prices",
    "snapshot_load": "Loading cached snapshot",
    "dependencies": "Loading public-data dependencies",
    "constituents": "Loading S&P 500 constituents and ETF list",
    "calendar": "Preparing completed trading sessions",
    "prices": "Downloading adjusted daily prices",
    "ranking": "Calculating cross-sectional momentum",
    "options": "Validating and joining offline options metrics",
    "config_parse": "Reading and validating pasted screener criteria",
    "config_save": "Saving screener configuration",
    "ota_auth": "Waiting for local hidden token input",
    "ota_fetch": "Fetching OTA screener pages (progress against page limit)",
    "reports": "Writing snapshots and reports",
    "dashboard": "Joining momentum, OTA metrics and prior-session ranks",
    "token_store": "Updating local OS credential store",
    "tradier_auth": "Loading local Tradier API key",
    "tradier_expirations": "Finding upcoming standard monthly expiration",
    "tradier_quote": "Fetching underlying quote",
    "tradier_chain": "Fetching monthly option chain",
    "summary": "Writing sanitized review summary",
}
COUNT_KEYS = {"tradier_matched","rows_profiled","ranked", "excluded", "symbols_requested", "symbols_received", "pages_requested", "pages_received", "matched", "candidates"}


class RunProgress:
    """One run, one exclusive JSONL log. Progress percentages are per stage.

Newline-delimited ASCII output works in terminals, IDEs and redirected stdout
without terminal probing or environment reads. Events are flushed immediately.
"""
    def __init__(self, log_directory: Path, run_id: str, command: str, profile: str,
                 revision: str, stream=None):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id) or not re.fullmatch(r"[a-f0-9]{64}", revision):
            raise ValueError("INVALID_LOG_METADATA")
        if command not in {"demo", "cached", "refresh", "ota-config", "ota-fetch", "ota-process", "dashboard", "dashboard-demo", "ota-token", "tradier-token", "tradier-probe"} or profile not in {"synthetic", "public", "unknown", "ota", "sandbox", "production"}:
            raise ValueError("INVALID_LOG_METADATA")
        self.run_id, self.command, self.profile, self.revision = run_id, command, profile, revision
        self.stream = sys.stdout if stream is None else stream
        self.started = self.stage_started = monotonic()
        self.stage_name, self.completed, self.total = "run", 0, None
        self.sequence = 0
        log_directory.mkdir(parents=True, exist_ok=True)
        self.path = log_directory / f"{run_id}.jsonl"
        self.log = self.path.open("x", encoding="utf-8", newline="\n")

    def _emit(self, event: str, level: str, message: str, *, counts=None, error_code=None):
        # Only internal calls provide event/level/message. Public methods accept
        # fixed stage/error codes and numeric counts; there is no free-text API.
        counts = {} if counts is None else counts
        if any(k not in COUNT_KEYS or type(v) is not int or v < 0 for k, v in counts.items()):
            raise ValueError("INVALID_LOG_COUNTS")
        elapsed = monotonic() - self.started
        percent = None if self.total is None else self.completed * 100 // self.total
        self.sequence += 1
        record = {"schema_version": 1, "timestamp_utc": datetime.now(timezone.utc).isoformat(),
                  "sequence": self.sequence, "level": level, "run_id": self.run_id,
                  "code_revision": self.revision, "command": self.command, "profile": self.profile,
                  "event": event, "stage": self.stage_name, "message": message,
                  "completed": self.completed, "total": self.total, "percent": percent,
                  "elapsed_seconds": round(elapsed, 3),
                  "stage_elapsed_seconds": round(monotonic() - self.stage_started, 3),
                  "counts": counts, "error_code": error_code}
        self.log.write(json.dumps(record, allow_nan=False) + "\n")
        self.log.flush()
        if percent is None:
            bar = "[....................]  --%"
        else:
            filled = percent // 5
            bar = f"[{'#' * filled}{'-' * (20 - filled)}] {percent:3}%"
        units = "batches" if self.stage_name == "prices" else "pages" if self.stage_name == "ota_fetch" else "steps"
        count_text = "" if self.total is None else f" ({self.completed}/{self.total} {units})"
        self.stream.write(f"{level:<7} {bar} {message}{count_text} | elapsed {elapsed:.1f}s\n")
        self.stream.flush()

    def begin(self):
        self._emit("run_started", "INFO", "Starting scanner")

    def set_profile(self, profile: str):
        if profile not in {"synthetic", "public"}:
            raise ValueError("INVALID_LOG_PROFILE")
        self.profile = profile
        self._emit("profile_resolved", "INFO", "Snapshot profile resolved")

    def start(self, stage: str, total: int = 1):
        if stage not in STAGES or stage == "run" or type(total) is not int or total <= 0:
            raise ValueError("INVALID_PROGRESS_STAGE")
        self.stage_name, self.completed, self.total = stage, 0, total
        self.stage_started = monotonic()
        self._emit("stage_started", "INFO", f"Currently running: {STAGES[stage]}")

    def advance(self, completed: int, *, counts=None):
        if self.total is None or type(completed) is not int or not self.completed <= completed <= self.total:
            raise ValueError("INVALID_PROGRESS_COUNT")
        self.completed = completed
        self._emit("stage_progress", "INFO", f"Currently running: {STAGES[self.stage_name]}", counts=counts)

    def finish(self, *, counts=None):
        if self.total is None:
            raise ValueError("NO_PROGRESS_STAGE")
        self.completed = self.total
        self._emit("stage_finished", "INFO", f"Completed: {STAGES[self.stage_name]}", counts=counts)

    def exclusions(self, count: int):
        self._emit("symbols_excluded", "WARNING", "Some symbols were excluded; review exclusions CSV",
                   counts={"excluded": count})

    def end(self, error_code: str | None = None, *, counts=None):
        if error_code is None:
            self.stage_name, self.completed, self.total = "run", 1, 1
            self.stage_started = self.started
            self._emit("run_finished", "INFO", "Run completed", counts=counts)
        else:
            # Keep the failing stage and its true completed count. No fake 100%.
            safe = error_code if error_code in SAFE_ERRORS else "SCAN_FAILED"
            cancelled = safe == "RUN_CANCELLED"
            self._emit("run_cancelled" if cancelled else "run_failed", "WARNING" if cancelled else "ERROR",
                       f"Run {'cancelled' if cancelled else 'failed'}: {safe}", counts=counts, error_code=safe)

    def close(self):
        self.log.close()
