"""Explicit catalog-only backup/restore; no credentials or provider execution.

A database snapshot defines the exact immutable file set. Completion manifests
are published last; interrupted directories are retained for user inspection.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from time import monotonic

from .catalog import Catalog, MIGRATIONS, MAX_BYTES, KINDS, confined, digest, encoded, identifier
from .core import DataError
from .ota_config import pairs
from .scan_service import code_revision

MAX_DB = 512_000_000
MAX_MANIFEST = 16_000_000
MAX_FILES = 100_000
MAX_TOTAL = 20_000_000_000
ERRORS = {'RECOVERY_INVALID', 'RECOVERY_CHANGED', 'RECOVERY_LIMIT',
          'RECOVERY_DESTINATION_EXISTS', 'RECOVERY_FAILED', 'RECOVERY_BUSY'}
MANIFEST = 'backup-manifest.json'


def local_path(value):
    path = Path(value).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise DataError('RECOVERY_INVALID')
    return path.resolve()


def fresh_directory(value):
    path = local_path(value)
    try:
        path.mkdir(parents=True, exist_ok=False, mode=0o700)
    except FileExistsError:
        raise DataError('RECOVERY_DESTINATION_EXISTS') from None
    return path


def sync_directory(path):
    if os.name == 'posix':
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def stream_file(path, limit, destination=None):
    """Bounded hashing/copying; payloads never enter diagnostics."""
    local_path(path)
    if not path.is_file() or path.stat().st_size > limit:
        raise DataError('RECOVERY_INVALID')
    size, hasher = 0, hashlib.sha256()
    with path.open('rb') as source:
        target = destination.open('xb') if destination is not None else None
        try:
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise DataError('RECOVERY_LIMIT')
                hasher.update(chunk)
                if target:
                    target.write(chunk)
            if target:
                target.flush(); os.fsync(target.fileno())
        finally:
            if target:
                target.close()
    return {'size':size, 'sha256':hasher.hexdigest()}


def publish_manifest(root, name, value):
    data = encoded(value)
    if len(data) > MAX_MANIFEST:
        raise DataError('RECOVERY_LIMIT')
    pending = root / (name + '.pending')
    with pending.open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    pending.rename(root/name)
    sync_directory(root)
    sync_directory(root.parent)


def schema_rows(db):
    return db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()


def inspect_database(path):
    """Accept only our exact known schema before running queries or migrations."""
    local_path(path)
    if not path.is_file() or path.stat().st_size > MAX_DB:
        raise DataError('RECOVERY_INVALID')
    with closing(sqlite3.connect(path, timeout=3, isolation_level=None)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        version = db.execute('PRAGMA user_version').fetchone()[0]
        if not 1 <= version <= len(MIGRATIONS):
            raise DataError('RECOVERY_INVALID')
        with closing(sqlite3.connect(':memory:')) as model:
            for migration in MIGRATIONS[:version]:
                model.executescript(migration.read_text(encoding='utf-8'))
            if schema_rows(db) != schema_rows(model):
                raise DataError('RECOVERY_INVALID')
        expected = [(i, digest(p.read_text(encoding='utf-8').encode('utf-8'))) for i,p in enumerate(MIGRATIONS[:version],1)]
        if db.execute('SELECT version,checksum FROM schema_migrations ORDER BY version').fetchall() != expected:
            raise DataError('RECOVERY_INVALID')
        if db.execute('PRAGMA quick_check').fetchall() != [('ok',)] or db.execute('PRAGMA foreign_key_check').fetchone():
            raise DataError('RECOVERY_INVALID')
        rows = db.execute('SELECT id,kind,relative_path,sha256,size,availability FROM artifacts ORDER BY id').fetchmany(MAX_FILES+1)
    if len(rows) > MAX_FILES:
        raise DataError('RECOVERY_LIMIT')
    files, total = [], 0
    for aid,kind,path,sha,size,status in rows:
        identifier(aid)
        if (kind not in KINDS or path != f'artifacts/catalog/files/{aid}.json'
                or status != 'available' or type(size) is not int or not 0 <= size <= MAX_BYTES
                or not isinstance(sha,str) or re.fullmatch('[a-f0-9]{64}',sha) is None):
            raise DataError('RECOVERY_INVALID')
        files.append({'id':aid,'kind':kind,'path':path,'size':size,'sha256':sha})
        total += size
    if total > MAX_TOTAL:
        raise DataError('RECOVERY_LIMIT')
    return version, files


def file_set(source_root, files, destination_root=None, progress=None):
    if progress:
        progress.start('recovery_files', max(1,len(files)))
    for number, entry in enumerate(files,1):
        source = confined(source_root,entry['path'])
        destination = None
        if destination_root is not None:
            destination = confined(destination_root,entry['path'])
            destination.parent.mkdir(parents=True,exist_ok=True)
        actual = stream_file(source,MAX_BYTES,destination)
        if actual != {key:entry[key] for key in ('size','sha256')}:
            raise DataError('RECOVERY_CHANGED')
        if progress:
            progress.advance(number,counts={'files':number})
    if destination_root is not None and files:
        sync_directory(destination_root/'artifacts/catalog/files')
    if progress:
        progress.finish(counts={'files':len(files)})


class RecoveryService:
    def __init__(self, root):
        self.root = local_path(root)

    def backup(self, destination, *, progress=None):
        source = Catalog(self.root)
        if not source.path.is_file():
            raise DataError('RECOVERY_INVALID')
        target = local_path(destination)
        if target == source.directory or source.directory in target.parents or target in self.root.parents or target == self.root:
            raise DataError('RECOVERY_INVALID')
        target = fresh_directory(target)
        copied = Catalog(target)
        copied.directory.mkdir(parents=True)
        if progress:
            progress.start('recovery_database')
        started = monotonic()
        def bounded(status, remaining, total):
            if monotonic()-started > 30:
                raise DataError('RECOVERY_BUSY')
            if total * page_size > MAX_DB:
                raise DataError('RECOVERY_LIMIT')
        # backup() captures a consistent committed DB, including journaled data.
        # Published files are immutable and never automatically deleted, so later
        # source registrations cannot change this snapshot's required file set.
        with source.connection() as db, closing(sqlite3.connect(copied.path)) as backup:
            db.execute('PRAGMA query_only=ON')
            page_size = db.execute('PRAGMA page_size').fetchone()[0]
            db.backup(backup,pages=256,progress=bounded,sleep=0.05)
        version, files = inspect_database(copied.path)
        database = stream_file(copied.path,MAX_DB)
        with copied.path.open('rb') as stream:
            os.fsync(stream.fileno())
        if progress:
            progress.finish()
        file_set(self.root,files,target,progress)
        sync_directory(copied.directory)
        sync_directory(target/'artifacts')
        manifest = {'schema_version':1,'scope':'catalog','created_at':datetime.now(timezone.utc).isoformat(),
                    'code_revision':code_revision(),'database_schema':version,'database':database,'files':files}
        publish_manifest(target,MANIFEST,manifest)
        return {'files':len(files),'bytes':database['size']+sum(f['size'] for f in files)}

    def verify(self, backup_root, *, progress=None):
        root = local_path(backup_root)
        path = confined(root,MANIFEST)
        if not path.is_file() or path.stat().st_size > MAX_MANIFEST:
            raise DataError('RECOVERY_INVALID')
        with path.open('rb') as stream:
            data = stream.read(MAX_MANIFEST+1)
        if len(data)>MAX_MANIFEST:
            raise DataError('RECOVERY_LIMIT')
        try:
            manifest = json.loads(data,object_pairs_hook=pairs)
            if (set(manifest) != {'schema_version','scope','created_at','code_revision','database_schema','database','files'}
                    or type(manifest['schema_version']) is not int or manifest['schema_version'] != 1
                    or manifest['scope'] != 'catalog' or type(manifest['database_schema']) is not int
                    or not isinstance(manifest['code_revision'],str)
                    or re.fullmatch('[a-f0-9]{64}',manifest['code_revision']) is None
                    or datetime.fromisoformat(manifest['created_at']).utcoffset() is None):
                raise ValueError
        except (TypeError,KeyError,ValueError):
            raise DataError('RECOVERY_INVALID') from None
        database = Catalog(root).path
        if stream_file(database,MAX_DB) != manifest['database']:
            raise DataError('RECOVERY_CHANGED')
        version, files = inspect_database(database)
        if version != manifest['database_schema'] or files != manifest['files']:
            raise DataError('RECOVERY_CHANGED')
        file_set(root,files,progress=progress)
        return manifest

    def restore(self, backup_root, destination, *, progress=None):
        manifest = self.verify(backup_root,progress=progress)
        source = local_path(backup_root)
        target = fresh_directory(destination)
        # Reserve a fresh workspace, and keep the catalog unpublished until all
        # copies, migrations and integrity checks succeed. Never merge/overwrite.
        staging = target/'.restore-pending'
        staged = Catalog(staging)
        staged.directory.mkdir(parents=True)
        actual = stream_file(Catalog(source).path,MAX_DB,staged.path)
        if actual != manifest['database']:
            raise DataError('RECOVERY_CHANGED')
        file_set(source,manifest['files'],staging,progress)
        inspect_database(staged.path)
        staged.initialize()
        inspect_database(staged.path)
        if progress:
            progress.start('recovery_database')
        sync_directory(staged.directory)
        (staging/'artifacts').rename(target/'artifacts')
        sync_directory(target)
        publish_manifest(target,'restore-complete.json',{'schema_version':1,'scope':'catalog',
                         'backup_database':manifest['database'],'code_revision':code_revision()})
        staging.rmdir()
        if progress:
            progress.finish()
        return {'files':len(manifest['files']),'bytes':manifest['database']['size']+sum(f['size'] for f in manifest['files'])}
