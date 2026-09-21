"""Explicit legacy daily-history import; originals are never modified.

Legacy ranks are limited evidence, not full calculation/replay snapshots. Batch
rollback deactivates future selection, preserving files and existing report pins.
"""
from datetime import date, datetime, timezone
import json
from itertools import islice
import math
import re
import sqlite3
import uuid

from .catalog import confined, digest, encoded, identifier
from .core import DataError, calculation_method, normalize_symbol
from .crs_history import method_key
from .ota_config import pairs

MAX_FILE = 8_000_000
MAX_TOTAL = 64_000_000
MAX_FILES = 5000


def validate_legacy(data, profile, session):
    try:
        value = json.loads(data, object_pairs_hook=pairs)
        if not isinstance(value, dict) or set(value) != {'as_of','profile','method','rows'}:
            raise DataError('HISTORY_LEGACY_UNSUPPORTED')
        if encoded(value['method']) != encoded(calculation_method()):
            raise DataError('HISTORY_LEGACY_UNSUPPORTED')
        if (profile not in ('public','synthetic') or value['profile'] != profile
                or value['as_of'] != session or date.fromisoformat(session).isoformat() != session
                or not isinstance(value['rows'],list) or len(value['rows']) > 60000):
            raise ValueError
        seen, ranks = set(), set()
        for row in value['rows']:
            if not isinstance(row,dict) or set(row) != {'symbol','group','rank','score','bias'}:
                raise ValueError
            if (normalize_symbol(row['symbol']) != row['symbol'] or row['symbol'] in seen
                    or row['group'] not in ('stock','etf') or type(row['rank']) is not int
                    or row['rank'] < 1 or (row['group'],row['rank']) in ranks
                    or type(row['score']) not in (int,float) or not math.isfinite(row['score'])
                    or row['bias'] not in ('long','short','neutral')):
                raise ValueError
            seen.add(row['symbol']); ranks.add((row['group'],row['rank']))
        return value
    except DataError:
        raise
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError):
        raise DataError('HISTORY_LEGACY_INVALID') from None


class LegacyHistory:
    def __init__(self,catalog):
        self.catalog = catalog

    def state(self, db, profile):
        try:
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version not in (1, 2, 3):
                raise DataError('HISTORY_UPGRADE_REQUIRED')
            active = [dict(row) for row in db.execute('SELECT l.artifact_id,l.price_session,a.sha256 FROM legacy_history l JOIN artifacts a ON a.id=l.artifact_id WHERE l.profile=? AND EXISTS (SELECT 1 FROM legacy_import_items i JOIN legacy_imports b ON b.id=i.batch_id WHERE i.artifact_id=l.artifact_id AND b.state=\'active\') ORDER BY l.price_session,l.artifact_id',(profile,))] if version >= 3 else []
            canonical = [dict(row) for row in db.execute('SELECT price_session,artifact_id FROM canonical_sessions WHERE profile=? AND method_key=? ORDER BY price_session',(profile,method_key()))] if version >= 2 else []
        except sqlite3.OperationalError:
            raise DataError('HISTORY_UPGRADE_REQUIRED') from None
        return {'active':active,'canonical':canonical}

    def _plan(self,profile,session=None):
        if profile not in ('public','synthetic'):
            raise DataError('HISTORY_INVALID')
        if session is not None:
            try:
                if date.fromisoformat(session).isoformat()!=session: raise ValueError
            except (TypeError,ValueError):
                raise DataError('HISTORY_INVALID') from None
        directory = confined(self.catalog.root,f'artifacts/history/{profile}')
        if self.catalog.path.exists():
            with self.catalog.connection() as db:
                state = self.state(db,profile)
        else:
            state = {'active':[],'canonical':[]}
        entries, blobs, size = [], {}, 0
        # Fixed layout only. A session option lets users isolate unsupported or
        # conflicting files without a general arbitrary-path ingestion endpoint.
        paths = list(islice(directory.glob(session+'.json' if session else '*.json'), MAX_FILES + 1))
        if len(paths) > MAX_FILES:
            raise DataError('HISTORY_IMPORT_LIMIT')
        for path in sorted(paths):
            path = confined(self.catalog.root,path.relative_to(self.catalog.root).as_posix())
            with path.open('rb') as stream:
                data = stream.read(MAX_FILE+1)
            size += len(data)
            if len(data)>MAX_FILE or size>MAX_TOTAL:
                raise DataError('HISTORY_IMPORT_LIMIT')
            sha = digest(data)
            status = 'importable'
            try:
                validate_legacy(data,profile,path.stem)
            except DataError as exc:
                status = 'unsupported' if exc.args[0]=='HISTORY_LEGACY_UNSUPPORTED' else 'invalid'
            if status == 'importable':
                existing = [row for row in state['active'] if row['price_session']==path.stem]
                if existing:
                    status = 'duplicate' if all(row['sha256']==sha for row in existing) else 'conflict'
                blobs[path.stem] = data
            entries.append({'session':path.stem,'sha256':sha,'status':status,
                            'catalog_precedence':any(row['price_session']==path.stem for row in state['canonical'])})
        plan = {'profile':profile,'session':session,'entries':entries,'state':state}
        counts = {key:sum(e['status']==key for e in entries) for key in ('importable','duplicate','conflict','unsupported','invalid')}
        return {'preview_id':digest(encoded(plan)), 'counts':counts, 'entries':entries,
                'limitations':'Ranks/scores only; original inputs, full membership, returns and code version unavailable.'}, blobs, state

    def preview(self,profile,session=None):
        return self._plan(profile,session)[0]

    def apply(self,profile,preview_id,session=None):
        if not isinstance(preview_id,str) or re.fullmatch('[a-f0-9]{64}',preview_id) is None:
            raise DataError('HISTORY_PREVIEW_STALE')
        plan,blobs,state = self._plan(profile,session)
        if preview_id != plan['preview_id']:
            raise DataError('HISTORY_PREVIEW_STALE')
        if any(plan['counts'][key] for key in ('conflict','unsupported','invalid')):
            raise DataError('HISTORY_IMPORT_BLOCKED')
        selected = [e for e in plan['entries'] if e['status']=='importable']
        if not selected:
            return {'batch_id':None,'imported':0,'duplicates':plan['counts']['duplicate']}
        # Publish immutable evidence first. A later failure can retain inactive
        # indexed copies, never a partially active batch. Originals stay untouched.
        self.catalog.initialize()
        copies = [(e,self.catalog.publish(blobs[e['session']],kind='legacy_history',profile=profile,
                                          observed_at=e['session'])) for e in selected]
        batch = uuid.uuid4().hex
        with self.catalog.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if self.state(db,profile)!=state:
                raise DataError('HISTORY_PREVIEW_STALE')
            db.execute('INSERT INTO legacy_imports VALUES (?,?,?,?,?,NULL)',
                       (batch,profile,preview_id,'active',datetime.now(timezone.utc).isoformat()))
            for entry,aid in copies:
                db.execute('INSERT OR IGNORE INTO legacy_history VALUES (?,?,?,?,?)',
                           (aid,profile,entry['session'],method_key(),f"{entry['session']}.json"))
                db.execute('INSERT INTO legacy_import_items VALUES (?,?)',(batch,aid))
            db.commit()
        return {'batch_id':batch,'imported':len(copies),'duplicates':plan['counts']['duplicate']}

    def rollback(self,batch_id):
        identifier(batch_id)
        with self.catalog.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT state FROM legacy_imports WHERE id=?',(batch_id,)).fetchone()
            if row is None:
                raise DataError('HISTORY_IMPORT_NOT_FOUND')
            changed = row['state']=='active'
            if changed:
                db.execute("UPDATE legacy_imports SET state='rolled_back',rolled_back_at=? WHERE id=?",
                           (datetime.now(timezone.utc).isoformat(),batch_id))
            db.commit()
        return {'batch_id':batch_id,'deactivated':int(changed)}

    def batches(self,profile):
        if profile not in ('synthetic','public'):
            raise DataError('HISTORY_INVALID')
        with self.catalog.connection() as db:
            return [dict(row) for row in db.execute('SELECT b.*,count(i.artifact_id) AS files FROM legacy_imports b LEFT JOIN legacy_import_items i ON i.batch_id=b.id WHERE b.profile=? GROUP BY b.id ORDER BY b.created_at DESC,b.id LIMIT 1000',(profile,))]

    def previous(self,artifact_id,snapshot):
        data = self.catalog.read(artifact_id,'legacy_history')
        with self.catalog.connection() as db:
            row = db.execute('SELECT * FROM legacy_history WHERE artifact_id=?',(artifact_id,)).fetchone()
        if (row is None or row['profile']!=snapshot['profile'] or row['method_key']!=method_key()
                or row['price_session']>=snapshot['as_of'] or row['price_session'] not in snapshot['sessions']):
            raise DataError('HISTORY_INVALID')
        return validate_legacy(data,snapshot['profile'],row['price_session'])
