"""Versioned personal views/preferences; shared by CLI and localhost adapters."""
from dataclasses import asdict,replace
from datetime import datetime,timezone
import json
import re
import uuid

from .catalog import encoded,digest,identifier
from .core import DataError
from .ota_config import pairs
from .report_selection import Selection,select_rows
from .report_expressions import expression_for_selection
from .report_service import ReportService
from .scan_service import code_revision

DEFAULTS = {'page_size':25,'display_timezone':'local'}
MAX_PAYLOAD = 65536


def preferences(value):
    if (not isinstance(value,dict) or set(value)!=set(DEFAULTS)
            or type(value['page_size']) is not int or value['page_size'] not in (25,50,100,250)
            or value['display_timezone'] not in ('local','utc')):
        raise DataError('SETTINGS_INVALID')
    return dict(value)


def selection_payload(selection):
    selection=replace(selection,filters=(),expression=expression_for_selection(selection),page=1)
    value=asdict(selection);value.pop('page');value.pop('filters')
    value['columns']=list(value['columns'])
    return {'version':1,'selection':value}


def saved_selection(value):
    try:
        if not isinstance(value,dict) or set(value)!= {'version','selection'} or type(value['version']) is not int or value['version']!=1:
            raise ValueError
        options=value['selection']
        if not isinstance(options,dict) or set(options)!=set(selection_payload(Selection())['selection']) or not isinstance(options['columns'],list):
            raise ValueError
        return Selection.from_mapping({**options,'columns':tuple(options['columns'])})
    except (TypeError,ValueError,KeyError):
        raise DataError('SETTINGS_INVALID') from None


class WorkspaceSettings:
    def __init__(self,catalog):
        self.catalog=catalog

    def current(self,kind,name):
        with self.catalog.connection() as db:
            row=db.execute('SELECT revision_id FROM workspace_heads WHERE kind=? AND name=?',(kind,name)).fetchone()
        return self.get(row[0]) if row else None

    def get(self,revision):
        identifier(revision)
        with self.catalog.connection() as db:
            row=db.execute('SELECT * FROM workspace_revisions WHERE id=?',(revision,)).fetchone()
        if row is None: raise DataError('SETTINGS_NOT_FOUND')
        row=dict(row)
        if digest(row['payload'].encode('utf-8'))!=row['payload_hash']:
            raise DataError('SETTINGS_INVALID')
        value=json.loads(row['payload'],object_pairs_hook=pairs)
        if row['kind']=='screener': saved_selection(value)
        elif row['kind']=='preferences': preferences(value)
        else: raise DataError('SETTINGS_INVALID')
        row['payload']=value
        return row

    def list(self):
        with self.catalog.connection() as db:
            return [dict(row) for row in db.execute('SELECT h.name,h.revision_id,r.created_at FROM workspace_heads h JOIN workspace_revisions r ON r.id=h.revision_id WHERE h.kind=\'screener\' ORDER BY h.name LIMIT 1000')]

    def history(self,kind,name):
        with self.catalog.connection() as db:
            return [dict(row) for row in db.execute('SELECT id,created_at,predecessor,source_artifact_id FROM workspace_revisions WHERE kind=? AND name=? ORDER BY rowid DESC LIMIT 100',(kind,name))]

    def preference_state(self):
        current=self.current('preferences','workspace')
        return (current['id'],current['payload']) if current else (None,dict(DEFAULTS))

    def save(self,kind,name,payload,*,expected=None,source=None):
        if (kind not in ('screener','preferences') or not isinstance(name,str)
                or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}',name) is None
                or name!=name.strip()):
            raise DataError('SETTINGS_INVALID')
        if expected is not None: identifier(expected)
        if kind=='preferences':
            if name!='workspace' or source is not None: raise DataError('SETTINGS_INVALID')
            payload=preferences(payload)
        else:
            if source is None: raise DataError('SETTINGS_INVALID')
            selection=saved_selection(payload)
            select_rows(ReportService(self.catalog).load(source),selection)
            payload=selection_payload(selection)
        data=encoded(payload)
        if len(data)>MAX_PAYLOAD: raise DataError('SETTINGS_INVALID')
        revision=uuid.uuid4().hex
        with self.catalog.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT revision_id FROM workspace_heads WHERE kind=? AND name=?',(kind,name)).fetchone()
            if (current[0] if current else None)!=expected: raise DataError('SETTINGS_CONFLICT')
            db.execute('INSERT INTO workspace_revisions VALUES (?,?,?,?,?,?,?,?,?)',
                       (revision,kind,name,data.decode('utf-8'),digest(data),expected,source,datetime.now(timezone.utc).isoformat(),code_revision()))
            db.execute('INSERT INTO workspace_heads VALUES (?,?,?) ON CONFLICT(kind,name) DO UPDATE SET revision_id=excluded.revision_id',(kind,name,revision))
            db.commit()
        return revision

    def apply(self,revision,result):
        row=self.get(revision)
        if row['kind']!='screener': raise DataError('SETTINGS_INVALID')
        selection=saved_selection(row['payload'])
        select_rows(result,selection)  # Reject unavailable fields instead of dropping rules.
        return selection
