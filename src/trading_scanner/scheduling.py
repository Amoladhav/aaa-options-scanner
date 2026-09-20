"""Personal schedule settings and transactional daily claims; no provider imports.

Adapters supply a dispatcher. A claim is durable before execution, preventing
repeat attempts after crashes; this is not exactly-once external execution.
"""
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
import json
import re
import sqlite3
import time as clock
from .run_ids import new_run_id

from .core import DataError

TASKS = ('ota', 'daily')


def zone(name):
    if name == 'UTC':
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except (ImportError, KeyError, ValueError):
        raise DataError('SCHEDULE_TIMEZONE_UNAVAILABLE') from None


def validate(settings, resolve_zone=zone):
    keys = {'schema_version', 'time', 'timezone', 'task', 'enabled', 'grace_minutes'}
    if not isinstance(settings, dict) or set(settings) != keys:
        raise DataError('SCHEDULE_INVALID')
    if type(settings['schema_version']) is not int or settings['schema_version'] != 1:
        raise DataError('SCHEDULE_INVALID')
    if not isinstance(settings['time'], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', settings['time']):
        raise DataError('SCHEDULE_INVALID')
    if not isinstance(settings['timezone'], str) or not re.fullmatch(r'[A-Za-z0-9_+/-]{1,100}', settings['timezone']):
        raise DataError('SCHEDULE_INVALID')
    if settings['task'] not in TASKS or type(settings['enabled']) is not bool:
        raise DataError('SCHEDULE_INVALID')
    if type(settings['grace_minutes']) is not int or not 1 <= settings['grace_minutes'] <= 180:
        raise DataError('SCHEDULE_INVALID')
    resolve_zone(settings['timezone'])
    return dict(settings)


def occurrence(day, settings, resolve_zone=zone):
    """Skip nonexistent wall times; use first occurrence of an ambiguous time."""
    tz = resolve_zone(settings['timezone'])
    local = datetime.combine(day, time.fromisoformat(settings['time'])).replace(tzinfo=tz, fold=0)
    utc = local.astimezone(timezone.utc)
    if utc.astimezone(tz).replace(tzinfo=None) != local.replace(tzinfo=None):
        return None
    return utc


def utc_now(value):
    if value.tzinfo is None or value.utcoffset() is None:
        raise DataError('SCHEDULE_INVALID')
    return value.astimezone(timezone.utc)


class ScheduleService:
    def __init__(self, root, *, resolve_zone=zone):
        self.path = root / 'artifacts/scheduler/schedule.sqlite3'
        self.resolve_zone = resolve_zone

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            if db.execute('PRAGMA user_version').fetchone()[0] not in (0, 1):
                raise DataError('SCHEDULE_STATE_INVALID')
            db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS jobs (day TEXT PRIMARY KEY, id TEXT UNIQUE NOT NULL, status TEXT NOT NULL, settings TEXT NOT NULL, due_utc TEXT NOT NULL, started_utc TEXT, finished_utc TEXT, elapsed_seconds REAL, error_code TEXT)')
            db.execute('PRAGMA user_version=1')
            yield db
        finally:
            if db.in_transaction:
                db.rollback()
            db.close()

    def configure(self, settings):
        checked = validate(settings, self.resolve_zone)
        with self.connection() as db:
            db.execute('INSERT INTO settings VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (json.dumps(checked),))
        return checked

    def set_enabled(self, enabled):
        if type(enabled) is not bool:
            raise DataError('SCHEDULE_INVALID')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            settings = self._settings(db)
            if settings is None:
                raise DataError('SCHEDULE_NOT_CONFIGURED')
            settings['enabled'] = enabled
            db.execute('UPDATE settings SET payload=? WHERE id=1', (json.dumps(settings),))
            db.commit()

    def _settings(self, db):
        row = db.execute('SELECT payload FROM settings WHERE id=1').fetchone()
        return None if row is None else validate(json.loads(row['payload']), self.resolve_zone)

    def view(self, now):
        now = utc_now(now)
        with self.connection() as db:
            settings = self._settings(db)
            jobs = [dict(row) for row in db.execute('SELECT day,id,status,due_utc,started_utc,finished_utc,elapsed_seconds,error_code FROM jobs ORDER BY day DESC LIMIT 30')]
        next_due = None
        if settings and settings['enabled']:
            today = now.astimezone(self.resolve_zone(settings['timezone'])).date()
            used = {row['day'] for row in jobs}
            for offset in range(370):
                day = today + timedelta(days=offset)
                due = occurrence(day, settings, self.resolve_zone)
                if day.isoformat() not in used and due is not None and now <= due + timedelta(minutes=settings['grace_minutes']):
                    next_due = due.astimezone(self.resolve_zone(settings['timezone'])).isoformat()
                    break
        return {'settings': settings, 'next_due_local': next_due,
                'blocked_by_running_job': any(row['status'] == 'running' for row in jobs), 'recent_jobs': jobs}

    def claim(self, now):
        now = utc_now(now)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            settings = self._settings(db)
            if settings is None or not settings['enabled']:
                return None
            if db.execute("SELECT 1 FROM jobs WHERE status='running'").fetchone():
                raise DataError('SCHEDULE_BUSY')
            day = now.astimezone(self.resolve_zone(settings['timezone'])).date()
            due = occurrence(day, settings, self.resolve_zone)
            if due is None or now < due or db.execute('SELECT 1 FROM jobs WHERE day=?', (day.isoformat(),)).fetchone():
                return None
            status = 'missed' if now > due + timedelta(minutes=settings['grace_minutes']) else 'running'
            job = {'day': day.isoformat(), 'id': new_run_id(), 'settings': settings, 'due_utc': due.isoformat()}
            db.execute('INSERT INTO jobs(day,id,status,settings,due_utc,started_utc) VALUES (?,?,?,?,?,?)',
                       (job['day'], job['id'], status, json.dumps(settings), job['due_utc'], now.isoformat() if status == 'running' else None))
            db.commit()
            return job if status == 'running' else None

    def finish(self, job_id, status, now, elapsed, error=None):
        if status not in ('succeeded', 'failed', 'cancelled') or error not in (None, 'SCHEDULE_TASK_FAILED', 'RUN_CANCELLED'):
            raise DataError('SCHEDULE_INVALID')
        with self.connection() as db:
            changed = db.execute("UPDATE jobs SET status=?,finished_utc=?,elapsed_seconds=?,error_code=? WHERE id=? AND status='running'",
                                 (status, utc_now(now).isoformat(), elapsed, error, job_id)).rowcount
            if changed != 1:
                raise DataError('SCHEDULE_STATE_INVALID')

    def acknowledge_stopped(self, day):
        # Only the user, after confirming the old worker has stopped, may recover.
        from datetime import date
        if date.fromisoformat(day).isoformat() != day:
            raise DataError('SCHEDULE_INVALID')
        with self.connection() as db:
            if db.execute("UPDATE jobs SET status='interrupted',error_code='RUN_CANCELLED' WHERE day=? AND status='running'", (day,)).rowcount != 1:
                raise DataError('SCHEDULE_STATE_INVALID')

    def tick(self, now, dispatch, *, wall=lambda: datetime.now(timezone.utc), monotonic=clock.monotonic):
        job = self.claim(now)
        if job is None:
            return None
        started = monotonic()
        status, error = 'failed', 'SCHEDULE_TASK_FAILED'
        try:
            result = dispatch(job)
            if result == 0:
                status, error = 'succeeded', None
            elif result == 130:
                status, error = 'cancelled', 'RUN_CANCELLED'
        except KeyboardInterrupt:
            status, error = 'cancelled', 'RUN_CANCELLED'
            raise
        finally:
            self.finish(job['id'], status, wall(), max(0, monotonic() - started), error)
        return {'id': job['id'], 'status': status, 'error_code': error}
