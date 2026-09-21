"""Private local artifact catalog; files are authoritative, SQL stores metadata.

Explicit construction/migration only. This module never indexes existing provider
files automatically, opens the scheduler, starts workers, or loads credentials.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

from .core import DataError, normalize_universe
from .run_ids import new_run_id, valid_run_id

KINDS = ('prices', 'ota', 'tradier', 'report', 'legacy_history')
PROFILES = ('synthetic', 'public', 'ota', 'sandbox', 'production')
MAX_BYTES = 220_000_000
MIGRATIONS = tuple(Path(__file__).with_name('migrations') / name
                   for name in ('001_catalog.sql', '002_crs_history.sql', '003_legacy_history.sql', '004_workspace_settings.sql'))


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identifier(value):
    if not isinstance(value, str) or re.fullmatch('[a-f0-9]{32}', value) is None:
        raise DataError('CATALOG_ID_INVALID')
    return value


def confined(root, relative):
    """No absolute paths, dot components, symlinks or Windows path ambiguities."""
    if not isinstance(relative, str) or '\\' in relative or ':' in relative:
        raise DataError('CATALOG_PATH_INVALID')
    parts = relative.split('/')
    if any(part in ('', '.', '..') for part in parts):
        raise DataError('CATALOG_PATH_INVALID')
    path = root
    for part in parts:
        path = path / part
        if path.is_symlink():
            raise DataError('CATALOG_PATH_INVALID')
    if root.resolve() not in path.resolve().parents:
        raise DataError('CATALOG_PATH_INVALID')
    return path


class Catalog:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = confined(self.root, 'artifacts/catalog')
        self.path = confined(self.root, 'artifacts/catalog/catalog.sqlite3')

    @contextmanager
    def connection(self):
        confined(self.root, 'artifacts/catalog/catalog.sqlite3')
        db = sqlite3.connect(self.path, timeout=3, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA synchronous=FULL')
            yield db
        finally:
            if db.in_transaction:
                db.rollback()
            db.close()

    def initialize(self, migrations=MIGRATIONS):
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > len(migrations):
                raise DataError('CATALOG_SCHEMA_INVALID')
            for number, migration in enumerate(migrations, 1):
                sql = migration.read_text(encoding='utf-8')
                checksum = digest(sql.encode('utf-8'))
                if number <= version:
                    row = db.execute('SELECT checksum FROM schema_migrations WHERE version=?', (number,)).fetchone()
                    if row is None or row['checksum'] != checksum:
                        raise DataError('CATALOG_SCHEMA_INVALID')
                    continue
                # execute(), not executescript(): retain our enclosing transaction
                # so failed DDL and the version marker roll back together.
                statement = ''
                for line in sql.splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        db.execute(statement)
                        statement = ''
                if statement.strip():
                    raise DataError('CATALOG_SCHEMA_INVALID')
                db.execute('INSERT INTO schema_migrations VALUES (?,?,?)',
                           (number, datetime.now(timezone.utc).isoformat(), checksum))
                db.execute(f'PRAGMA user_version={number}')  # trusted integer, not external SQL
            db.commit()

    def list_artifacts(self, kind=None):
        if kind is not None and kind not in KINDS:
            raise DataError('CATALOG_KIND_INVALID')
        with self.connection() as db:
            rows = db.execute('SELECT a.id,a.kind,a.run_id,a.availability,r.profile,r.started_at,r.state,r.master_id FROM artifacts a JOIN runs r ON r.id=a.run_id WHERE (? IS NULL OR a.kind=?) ORDER BY r.started_at DESC,a.id', (kind, kind)).fetchall()
        return [dict(row) for row in rows]

    def runs(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM runs ORDER BY started_at DESC,id')]

    def inputs(self, run_id):
        with self.connection() as db:
            return [row[0] for row in db.execute('SELECT artifact_id FROM run_inputs WHERE run_id=? ORDER BY ordinal', (run_id,))]

    def record(self, artifact_id):
        identifier(artifact_id)
        with self.connection() as db:
            row = db.execute('SELECT a.*,r.profile FROM artifacts a JOIN runs r ON r.id=a.run_id WHERE a.id=?', (artifact_id,)).fetchone()
        if row is None:
            raise DataError('CATALOG_NOT_FOUND')
        return dict(row)

    def read(self, artifact_id, kind=None):
        row = self.record(artifact_id)
        if kind is not None and row['kind'] != kind:
            raise DataError('CATALOG_KIND_INVALID')
        # Validate the exact managed layout even if metadata was tampered with.
        expected = f'artifacts/catalog/files/{identifier(artifact_id)}.json'
        if row['relative_path'] != expected or row['availability'] != 'available':
            raise DataError('CATALOG_ARTIFACT_UNAVAILABLE')
        path = confined(self.root, expected)
        try:
            with path.open('rb') as stream:
                data = stream.read(MAX_BYTES + 1)
        except OSError:
            raise DataError('CATALOG_ARTIFACT_UNAVAILABLE') from None
        if len(data) > MAX_BYTES or len(data) != row['size'] or digest(data) != row['sha256']:
            raise DataError('CATALOG_ARTIFACT_CHANGED')
        return data

    def publish(self, data, *, kind, profile, input_ids=(), run_id=None,
                master=None, observed_at=None, settings=None, state='succeeded', history=None):
        """Publish an immutable copy, then register it. Orphans remain recoverable.

        Inputs are already validated by application services. Exact bytes are
        retained on ingestion; report serialization uses encoded(). Indexing the
        same source kind/profile/bytes is idempotent; report runs stay append-only.
        """
        if kind not in KINDS or profile not in PROFILES or state not in ('succeeded', 'partial'):
            raise DataError('CATALOG_INPUT_INVALID')
        if not isinstance(data, bytes) or len(data) > MAX_BYTES:
            raise DataError('CATALOG_INPUT_INVALID')
        run_id = new_run_id() if run_id is None else run_id
        if not valid_run_id(run_id) or len(set(input_ids)) != len(input_ids):
            raise DataError('CATALOG_INPUT_INVALID')
        for aid in input_ids:
            self.read(aid)
        content_hash = digest(data)
        if history is not None:
            from .crs_history import validate_history
            if kind != 'report':
                raise DataError('HISTORY_INVALID')
            validate_history(history, data, profile)
        if kind != 'report':
            with self.connection() as db:
                existing = db.execute('SELECT a.id FROM artifacts a JOIN runs r ON r.id=a.run_id WHERE a.kind=? AND a.sha256=? AND r.profile=?', (kind, content_hash, profile)).fetchone()
            if existing:
                self.read(existing['id'])
                return existing['id']
        aid = uuid.uuid4().hex
        relative = f'artifacts/catalog/files/{aid}.json'
        path = confined(self.root, relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = confined(self.root, f'artifacts/catalog/files/{aid}.pending')
        # Exclusive temporary names and immutable UUID destinations; never overwrite
        # user inputs. fsync the file before publishing, and the directory on POSIX.
        with temporary.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.rename(path)
        if os.name == 'posix':
            fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        now = datetime.now(timezone.utc).isoformat()
        from .scan_service import code_revision
        master_key, members = None, None
        if master is not None:
            members = normalize_universe(master)
            from .tradier_batch import master_id
            master_key = master_id(members)
        settings_key = None
        if settings is not None:
            from .dashboard import filters_checked
            settings = filters_checked(settings)
            settings_key = digest(encoded(settings))
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if members is not None:
                db.execute('INSERT OR IGNORE INTO master_versions VALUES (?,?,?)', (master_key, observed_at, master_key))
                for member in members:
                    db.execute('INSERT OR IGNORE INTO master_members VALUES (?,?,?)', (master_key, member['symbol'], encoded(member).decode()))
            if settings_key:
                db.execute('INSERT OR IGNORE INTO settings_revisions VALUES (?,?,?,NULL)', (settings_key, encoded(settings).decode(), settings_key))
            provider = {'prices':'public', 'ota':'ota', 'tradier':'tradier', 'report':'derived', 'legacy_history':'legacy'}[kind]
            db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (run_id, 'local', profile, provider, 'report' if kind=='report' else 'index', state,
                        now, now, str(datetime.now().astimezone().tzinfo), observed_at, code_revision(), settings_key, master_key))
            db.execute('INSERT INTO artifacts VALUES (?,?,?,?,?,?,?,?)',
                       (aid, run_id, kind, relative, 1, content_hash, len(data), 'available'))
            for ordinal, source in enumerate(input_ids):
                db.execute('INSERT INTO run_inputs VALUES (?,?,?)', (run_id, source, ordinal))
            if history is not None:
                from .crs_history import register_history
                register_history(db, run_id, aid, history)
            db.commit()
        return aid

    def reconcile(self):
        """Aggregate evidence only; do not auto-adopt/delete orphan files."""
        counts = {'available':0, 'missing':0, 'changed':0, 'orphans':0, 'pending':0}
        with self.connection() as db:
            rows = [dict(row) for row in db.execute('SELECT * FROM artifacts')]
        known = {row['id'] for row in rows}
        for row in rows:
            status = 'available'
            try:
                self.read(row['id'])
            except DataError as exc:
                status = 'missing' if exc.args[0] == 'CATALOG_ARTIFACT_UNAVAILABLE' else 'changed'
            counts[status] += 1
        directory = confined(self.root, 'artifacts/catalog/files')
        if directory.exists():
            for path in directory.iterdir():
                if path.suffix == '.pending':
                    counts['pending'] += 1
                elif path.suffix == '.json' and path.stem not in known:
                    counts['orphans'] += 1
        return counts
