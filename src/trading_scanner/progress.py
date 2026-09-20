"""Shared stdout progress and structured, allowlisted run events.

Write directly to the original stdout stream so application progress remains
visible while noisy provider stdout/stderr and logging are suppressed. No raw
log message, exception, provider identifier, or arbitrary metadata is accepted.
"""
from datetime import datetime, timezone, timedelta
import math
import json
import os
from pathlib import Path
from .run_ids import valid_run_id
import re
import sys
from time import monotonic

from .credentials import ERRORS as CREDENTIAL_ERRORS

SAFE_ERRORS = CREDENTIAL_ERRORS | {"OTA_REPORT_INPUT_INVALID", "OTA_REPORT_INPUT_MISSING", "OTA_REPORT_FAILED", "SCHEDULE_TASK_FAILED", "THROTTLE_BUSY", "THROTTLE_STATE_INVALID", "THROTTLE_COOLDOWN_ACTIVE", "THROTTLE_CIRCUIT_OPEN", "PUBLIC_NETWORK_ERROR", "PUBLIC_ACCESS_REJECTED", "PUBLIC_RATE_LIMITED", "PUBLIC_HTTP_ERROR","TRADIER_BATCH_PARTIAL","SCAN_FAILED", "DEPENDENCY_UNAVAILABLE", "CONSTITUENTS_SCHEMA_CHANGED",
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
    "report_model": "Preparing saved-data report and field profile",
    "scheduled_job": "Running scheduled workflow",
    "throttle_wait": "Waiting for conservative provider pacing",
    "tradier_batch": "Fetching Tradier data for master-list symbols",
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
COUNT_KEYS = {"ota_received", "ota_outside_master", "fields", "mixed_type_fields", "missing_cells", "null_cells", "blank_strings", "negative_values", "http_requests", "retries", "rate_limit_events", "throttle_wait_seconds","rows", "chains_received","master_symbols","symbols_failed", "requests","tradier_matched","rows_profiled","ranked", "excluded", "symbols_requested", "symbols_received", "pages_requested", "pages_received", "matched", "candidates"}


class RunProgress:
    """Structured durable events and a single transient terminal progress line.

    Local wall time is for people; UTC and monotonic elapsed time are retained
    for correlation and durations. Redirected output never contains control codes.
    """
    def __init__(self, log_directory: Path, run_id: str, command: str, profile: str,
                 revision: str, stream=None):
        if not valid_run_id(run_id) or not re.fullmatch(r"[a-f0-9]{64}", revision):
            raise ValueError("INVALID_LOG_METADATA")
        if command not in {"ota-report", "ota-report-demo", "schedule-run", "demo", "cached", "refresh", "ota-config", "ota-fetch", "ota-process", "dashboard", "dashboard-demo", "ota-token", "tradier-token", "tradier-probe", "tradier-fetch"} or profile not in {"synthetic", "public", "unknown", "ota", "sandbox", "production"}:
            raise ValueError("INVALID_LOG_METADATA")
        self.run_id, self.command, self.profile, self.revision = run_id, command, profile, revision
        self.stream = sys.stdout if stream is None else stream
        self.started = self.stage_started = monotonic()
        self.stage_name, self.completed, self.total = "run", 0, None
        self.forecast = None
        self.detail = None
        self.sequence = 0
        self.last_counts = {}
        self.line_width = 0
        try:
            self.interactive = self.stream.isatty()
        except (AttributeError, OSError):
            self.interactive = False
        try:
            self.columns = max(2, os.get_terminal_size(self.stream.fileno()).columns)
        except (AttributeError, OSError, ValueError):
            self.columns = 120
        log_directory.mkdir(parents=True, exist_ok=True)
        self.path = log_directory / f"{run_id}.jsonl"
        self.log = self.path.open("x", encoding="utf-8", newline="\n")
        self.error_path = log_directory / f"{run_id}.errors.log"
        try:
            self.error_log = self.error_path.open("x", encoding="utf-8", newline="\n")
        except OSError:
            self.log.close()
            raise

    def pause(self):
        """Clear transient output before a prompt or ordinary output line."""
        if self.line_width:
            self.stream.write("\r" + " " * self.line_width + "\r")
            self.stream.flush()
            self.line_width = 0

    def _line(self, message, level="INFO"):
        self.pause()
        stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        self.stream.write(f"{stamp} {level:<7} [{self.command}/{self.profile}] {message}\n")
        self.stream.flush()

    def _emit(self, event: str, level: str, message: str, *, counts=None, error_code=None):
        # Only internal calls provide event/level/message. Public methods accept
        # fixed stage/error codes and numeric counts; there is no free-text API.
        counts = {} if counts is None else counts
        if any(k not in COUNT_KEYS or type(v) is not int or v < 0 for k, v in counts.items()):
            raise ValueError("INVALID_LOG_COUNTS")
        self.last_counts.update(counts)
        elapsed = monotonic() - self.started
        utc_stamp = datetime.now(timezone.utc)
        local_stamp = utc_stamp.astimezone()
        percent = None if self.total is None else self.completed * 100 // self.total
        self.sequence += 1
        record = {"schema_version": 2, "timestamp_utc": utc_stamp.isoformat(),
                  "timestamp": local_stamp.isoformat(), "timezone": local_stamp.tzname(),
                  "sequence": self.sequence, "level": level, "run_id": self.run_id,
                  "code_revision": self.revision, "command": self.command, "profile": self.profile,
                  "event": event, "stage": self.stage_name, "step": self.detail or self.stage_name, "message": message,
                  "completed": self.completed, "total": self.total, "percent": percent,
                  "elapsed_seconds": round(elapsed, 3),
                  "stage_elapsed_seconds": round(monotonic() - self.stage_started, 3),
                  "counts": counts, "error_code": error_code, "estimate": self.forecast}
        self.log.write(json.dumps(record, allow_nan=False) + "\n")
        self.log.flush()
        if level in ("WARNING", "ERROR"):
            self.error_log.write(json.dumps(record, allow_nan=False) + "\n")
            self.error_log.flush()
        if percent is None:
            bar = "[....................]  --%"
        else:
            filled = percent // 5
            bar = f"[{'#' * filled}{'-' * (20 - filled)}] {percent:3}%"
        units = "symbols" if self.stage_name == "tradier_batch" else "batches" if self.stage_name == "prices" else "pages" if self.stage_name == "ota_fetch" else "steps"
        count_text = "" if self.total is None else f" ({self.completed}/{self.total} {units})"
        line = f"{local_stamp.isoformat(timespec='seconds')} {level:<7} {bar} {message}{count_text} | elapsed {elapsed:.1f}s"
        # Prompts need a normal line; no carriage return may interfere with input.
        transient = (self.interactive and event in ("stage_started", "stage_progress", "estimate")
                     and self.stage_name not in ("ota_auth", "tradier_auth", "token_store", "config_parse"))
        if transient:
            # Leave one column unused to prevent wrapping at the right margin.
            compact = f"{local_stamp.isoformat(timespec='seconds')} {level} {bar} {self.completed}/{self.total} {STAGES[self.detail or self.stage_name]}"
            if self.columns < 110:
                step = (self.detail or self.stage_name).replace("_", " ")
                compact = f"{local_stamp.strftime('%H:%M:%S%z')} {bar} {self.completed}/{self.total} {step}"
            if self.columns < 75:
                compact = f"{self.completed}/{self.total} {step} {percent if percent is not None else '--'}%"
            if self.forecast and self.columns >= 110:
                compact = f"{local_stamp.strftime('%H:%M:%S%z')} {self.completed}/{self.total} {bar} {STAGES[self.detail or self.stage_name]} | ETA ~{math.ceil(self.forecast['remaining_seconds']/60)}m"
            compact = compact[:self.columns - 1]
            self.stream.write("\r" + compact + " " * max(0, self.line_width - len(compact)))
            self.line_width = len(compact)
            self.stream.flush()
        else:
            self.pause()
            self.stream.write(line + "\n")
            self.stream.flush()

    def begin(self):
        self._emit("run_started", "INFO", "Starting scanner")
        self._line(f"Run log: {self.path}")
        self._line(f"Error log: {self.error_path}")

    def set_profile(self, profile: str):
        if profile not in {"synthetic", "public"}:
            raise ValueError("INVALID_LOG_PROFILE")
        self.profile = profile
        self._emit("profile_resolved", "INFO", "Snapshot profile resolved")

    def start(self, stage: str, total: int = 1):
        if stage not in STAGES or stage == "run" or type(total) is not int or total <= 0:
            raise ValueError("INVALID_PROGRESS_STAGE")
        self.detail = None
        self.stage_name, self.completed, self.total = stage, 0, total
        self.stage_started = monotonic()
        self._emit("stage_started", "INFO", f"Currently running: {STAGES[stage]}")

    def advance(self, completed: int, *, counts=None, detail=None):
        if self.total is None or type(completed) is not int or not self.completed <= completed <= self.total:
            raise ValueError("INVALID_PROGRESS_COUNT")
        if detail is not None and detail not in STAGES:
            raise ValueError("INVALID_PROGRESS_STAGE")
        self.detail = detail
        self.completed = completed
        self._emit("stage_progress", "INFO", f"Currently running: {STAGES[detail or self.stage_name]}", counts=counts)

    def finish(self, *, counts=None):
        if self.total is None:
            raise ValueError("NO_PROGRESS_STAGE")
        self.detail = None
        self.completed = self.total
        self._emit("stage_finished", "INFO", f"Completed: {STAGES[self.stage_name]}", counts=counts)

    def estimate(self, seconds, interval, *, provisional=True, announce=False):
        if type(seconds) not in (float, int) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("INVALID_ESTIMATE")
        if type(interval) not in (float, int) or not math.isfinite(interval) or interval <= 0:
            raise ValueError("INVALID_ESTIMATE")
        first = announce or self.forecast is None
        try:
            finish = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).astimezone().isoformat(timespec='seconds')
        except OverflowError:
            finish = 'beyond_display_range'
        self.forecast = {'remaining_seconds': math.ceil(seconds), 'completion_local': finish,
                         'interval_seconds': interval, 'provisional': bool(provisional)}
        message = f"Estimated completion: {finish} | remaining ~{math.ceil(seconds / 60)}m | pacing {interval:g}s | {'provisional workload' if provisional else 'known workload'}"
        if first:
            self._line(message)
        self._emit('estimate', 'INFO', message)

    def error(self, code, *, counts=None):
        safe = code if code in SAFE_ERRORS else "SCAN_FAILED"
        self._emit("operation_error", "ERROR", f"Operation error: {safe}", counts=counts, error_code=safe)

    def exclusions(self, count: int):
        self._emit("symbols_excluded", "WARNING", "Some symbols were excluded; review exclusions CSV",
                   counts={"excluded": count})

    def end(self, error_code: str | None = None, *, counts=None):
        counts = {**self.last_counts, **({} if counts is None else counts)}
        if error_code is None:
            self.detail = None
            self.stage_name, self.completed, self.total = "run", 1, 1
            self.stage_started = self.started
            self._emit("run_finished", "INFO", "Run completed", counts=counts)
        else:
            # Keep the failing stage and its true completed count. No fake 100%.
            safe = error_code if error_code in SAFE_ERRORS else "SCAN_FAILED"
            cancelled = safe == "RUN_CANCELLED"
            self._emit("run_cancelled" if cancelled else "run_failed", "WARNING" if cancelled else "ERROR",
                       f"Run {'cancelled' if cancelled else 'failed'}: {safe}", counts=counts, error_code=safe)

        status = "completed" if error_code is None else "cancelled" if error_code == "RUN_CANCELLED" else "partial" if error_code == "TRADIER_BATCH_PARTIAL" else "failed"
        count_text = " ".join(f"{key}={value}" for key, value in sorted(counts.items()))
        self._line(f"Summary: status={status} elapsed={monotonic() - self.started:.1f}s {count_text}")
        self._line(f"Run log: {self.path}")
        self._line(f"Error log: {self.error_path}")

    def close(self):
        try:
            self.pause()
        finally:
            try:
                self.log.close()
            finally:
                self.error_log.close()
