"""Local, provider-scoped pacing and conservative feedback; no credential access.

A filesystem lease serializes jobs in one workspace. It is deliberately broader
than a credential: multiple keys cannot accidentally increase a provider's rate.
"""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import time
import uuid

from .core import DataError
from .dashboard import atomic_json

DEFAULTS = {'tradier-production': 2.0, 'tradier-sandbox': 3.0,
            'ota': 5.0, 'yahoo': 10.0, 'wikipedia': 2.0}


def finite(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def retry_deadline(value, now):
    if not isinstance(value, str) or len(value) > 128:
        return now
    try:
        seconds = float(value)
        if math.isfinite(seconds) and seconds >= 0:
            return min(1e100, now + seconds)
    except ValueError:
        pass
    try:
        stamp = parsedate_to_datetime(value)
        return max(now, stamp.timestamp()) if stamp.tzinfo is not None else now
    except (ValueError, TypeError, OverflowError):
        return now


class Governor:
    def __init__(self, directory, provider, *, progress=None, clock=None, wall=None, sleep=None):
        if provider not in DEFAULTS:
            raise DataError('THROTTLE_STATE_INVALID')
        self.directory, self.provider, self.progress = directory, provider, progress
        self.clock, self.wall, self.sleep = clock or time.monotonic, wall or time.time, sleep or time.sleep
        self.path = directory / (provider + '.json')
        self.lock = directory / (provider + '.lock')
        self.state = {'schema_version': 1, 'interval_seconds': DEFAULTS[provider],
                      'cooldown_until': 0.0, 'latency_seconds': 5.0, 'requests_per_unit': 14.0 if provider.startswith('tradier') else 80.0 if provider == 'yahoo' else 1.0,
                      'runs': 0, 'last_duration_seconds': 0.0}
        self.requests = self.retries = self.rate_limits = 0
        self.wait_seconds = 0.0
        self.completed_units = 0
        self.units = None
        self.started = self.clock()
        self.blocked = None
        self.last_status = None
        self.held = False
        self.prior_counts = {key: progress.last_counts.get(key, 0) if progress else 0 for key in self.counts()}

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            with self.lock.open('x', encoding='utf-8') as stream:
                stream.write('active local fetch; remove only after confirming no process is running\n')
        except FileExistsError:
            raise DataError('THROTTLE_BUSY') from None
        self.held = True
        try:
            if self.path.exists():
                with self.path.open('rb') as stream:
                    raw = stream.read(8193)
                loaded = json.loads(raw)
                if len(raw) > 8192 or not isinstance(loaded, dict) or set(loaded) != set(self.state):
                    raise ValueError()
                if loaded['schema_version'] != 1 or any(not finite(v) for k, v in loaded.items() if k != 'schema_version'):
                    raise ValueError()
                self.state = loaded
                self.state['interval_seconds'] = max(DEFAULTS[self.provider], loaded['interval_seconds'])
            self._save()
            return self
        except (ValueError, TypeError, OverflowError):
            self.lock.unlink(missing_ok=True)
            self.held = False
            raise DataError('THROTTLE_STATE_INVALID') from None
        except BaseException:
            self.lock.unlink(missing_ok=True)
            self.held = False
            raise

    def _save(self):
        atomic_json(self.path, self.state)

    def __exit__(self, *args):
        try:
            atomic_json(self.directory / 'history' / f'{self.provider}-{uuid.uuid4().hex}.json',
                        {'schema_version': 1, 'provider': self.provider,
                         'finished_at_utc': datetime.now(timezone.utc).isoformat(),
                         'fetch_duration_seconds': max(0.0, self.clock() - self.started),
                         'status': 'interrupted_or_failed' if self.blocked or (args and args[0]) else 'finished',
                         'interval_seconds': self.state['interval_seconds'], **self.counts()})
            if not args or args[0] is None:
                self.units = self.completed_units
                self.estimate()
            self.state['runs'] += 1
            self.state['last_duration_seconds'] = max(0.0, self.clock() - self.started)
            self._save()
            if self.progress:
                self.progress.advance(self.progress.completed, counts=self.progress_counts(), detail=self.progress.detail)
        finally:
            if self.held:
                self.lock.unlink(missing_ok=True)
                self.held = False

    def counts(self):
        return {'http_requests': self.requests, 'retries': self.retries,
                'rate_limit_events': self.rate_limits, 'throttle_wait_seconds': math.ceil(self.wait_seconds)}

    def progress_counts(self):
        return {key: value + self.prior_counts[key] for key, value in self.counts().items()}

    def plan(self, units, *, provisional=True):
        self.units = units
        self.provisional = provisional
        self.estimate(announce=True)

    def unit_done(self):
        self.completed_units += 1
        if self.requests:
            # Learn workload/latency for ETA, never derive a faster request rate.
            observed = self.requests / self.completed_units
            self.state['requests_per_unit'] = max(observed, self.state['requests_per_unit'] * .9)
        self.estimate()

    def estimate(self, *, announce=False):
        if self.progress and self.units is not None:
            remaining = max(0, self.units - self.completed_units)
            estimate = (remaining * self.state['requests_per_unit'] *
                        (self.state['interval_seconds'] + max(5, self.state['latency_seconds'])) * 1.5)
            if remaining:
                estimate += max(0, self.state['cooldown_until'] - self.wall())
            self.progress.estimate(estimate, self.state['interval_seconds'], provisional=self.provisional, announce=announce)

    def observe(self, status, retry_after=None, available=None, expiry=None, allowed=None):
        self.last_status = status
        now = self.wall()
        if status in (429, 503):
            self.state['cooldown_until'] = max(self.state['cooldown_until'], retry_deadline(retry_after, now))
        if self.provider.startswith('tradier'):
            try:
                quota = int(allowed) if isinstance(allowed, str) else 0
                if 0 < quota < 100000:
                    self.state['interval_seconds'] = max(self.state['interval_seconds'], 70 / quota)
                if isinstance(available, str) and int(available) <= 2:
                    reset = float(expiry) if isinstance(expiry, str) else now + 65
                    if not math.isfinite(reset):
                        reset = now + 65
                    self.state['cooldown_until'] = max(self.state['cooldown_until'], now + 65, reset + 5)
            except (ValueError, OverflowError):
                pass
        self._save()

    def check(self):
        if self.blocked:
            raise DataError(self.blocked)

    def call(self, operation, *, retries=1):
        self.check()
        if not self.held:
            raise DataError('THROTTLE_STATE_INVALID')
        for attempt in range(retries + 1):
            delay = max(self.state['interval_seconds'], self.state['cooldown_until'] - self.wall())
            if delay > 900:
                self.blocked = 'THROTTLE_COOLDOWN_ACTIVE'
                raise DataError(self.blocked)
            detail = self.progress.detail if self.progress else None
            while delay > 0:
                chunk = min(delay, 10.0)
                if self.progress:
                    self.progress.advance(self.progress.completed, detail='throttle_wait', counts=self.progress_counts())
                before = self.clock()
                self.sleep(chunk)
                self.wait_seconds += max(0.0, self.clock() - before)
                delay -= chunk
            if self.progress:
                self.progress.advance(self.progress.completed, detail=detail, counts=self.progress_counts())
            started = self.clock()
            self.requests += 1
            self.last_status = None
            try:
                value = operation()
            except Exception as exc:
                code = exc.args[0] if isinstance(exc, DataError) and len(exc.args) == 1 else None
                transient = self.last_status in (429, 500, 502, 503, 504) or code in ('OTA_NETWORK_ERROR', 'TRADIER_NETWORK_ERROR', 'PUBLIC_NETWORK_ERROR')
                if transient:
                    if self.progress:
                        self.progress.error(code or 'THROTTLE_CIRCUIT_OPEN', counts=self.progress_counts())
                    self.rate_limits += int(self.last_status == 429)
                    self.state['interval_seconds'] = max(self.state['interval_seconds'], min(3600, self.state['interval_seconds'] * 2))
                    self.state['cooldown_until'] = max(self.state['cooldown_until'], self.wall() + (300 if self.last_status == 429 else 30) * (attempt + 1))
                    self._save()
                    self.estimate()
                    if attempt < retries:
                        self.retries += 1
                        continue
                    self.blocked = code or 'THROTTLE_CIRCUIT_OPEN'
                elif self.last_status in (401, 403):
                    self.blocked = code or 'PUBLIC_ACCESS_REJECTED'
                raise
            finally:
                latency = max(0.0, self.clock() - started)
                self.state['latency_seconds'] = max(latency, self.state['latency_seconds'] * .95)
                self._save()
            return value
