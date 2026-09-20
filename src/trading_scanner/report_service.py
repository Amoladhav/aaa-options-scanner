"""Shared saved-data composition, selection and exports for CLI and local web."""
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import io
import json
import math

from .catalog import encoded
from .core import DataError
from .dashboard import combine, attach_tradier, FILTER_DEFAULTS, EXTRA_FIELDS, TRADIER_FIELDS
from .ota_config import pairs
from .report import FIELDS, csv_cell


def compose_report(snapshot, ota, *, probes=(), filters=None, now=None, previous=None):
    """One calculation/join implementation; no filesystem, providers or printing."""
    now = now or datetime.now(timezone.utc)
    missing = ota is None
    if missing:
        # Empty internal adapter allows CRS-only reports without inventing metrics.
        ota = {'source':'synthetic' if snapshot['profile']=='synthetic' else 'ota',
               'retrieved_at':now.isoformat(),'coverage':'synthetic' if snapshot['profile']=='synthetic' else 'short_page_observed','rows':[]}
    result = combine(snapshot,ota,filters,now=now,previous=previous)
    attach_tradier(result,probes)
    if missing:
        result['ota_metadata']={'source':None,'retrieved_at':None,'coverage':'not_supplied','observation_timestamp':None,'methodology':'unverified'}
        for row in result['combined']:
            row['ota_status']='not_supplied'
    return result


@dataclass(frozen=True)
class Selection:
    search: str = ''
    group: str = 'all'
    tail: str = 'all'
    percent: float = 10
    sort: str = 'score'
    direction: str = 'desc'
    page: int = 1
    page_size: int = 25

    def __post_init__(self):
        if (not isinstance(self.search,str) or len(self.search)>100
                or self.group not in ('all','stock','etf','sector')
                or self.tail not in ('all','top','bottom','both')
                or type(self.percent) not in (int,float) or not math.isfinite(self.percent) or not .1<=self.percent<=50
                or self.sort not in ('symbol','company','score','percentile','rank')
                or self.direction not in ('asc','desc')
                or type(self.page) is not int or not 1<=self.page<=100000
                or self.page_size not in (25,50,100,250)):
            raise DataError('REPORT_SELECTION_INVALID')

    @classmethod
    def from_mapping(cls, values):
        allowed=set(cls.__dataclass_fields__)
        if set(values)-allowed:
            raise DataError('REPORT_SELECTION_INVALID')
        options=dict(values)
        try:
            for key in ('page','page_size'):
                if key in options: options[key]=int(options[key])
            if 'percent' in options: options['percent']=float(options['percent'])
            return cls(**options)
        except (TypeError,ValueError):
            raise DataError('REPORT_SELECTION_INVALID') from None


def select_rows(result, selection):
    rows=[]
    for row in result['combined']:
        if selection.group!='all' and not (row['group']==selection.group or selection.group=='sector' and row.get('sector_etf')):
            continue
        # Search is deliberately symbol/company/sector, stable across table columns.
        if selection.search.casefold() not in ' '.join(str(row.get(k,'')) for k in ('symbol','company','sector')).casefold():
            continue
        p=row.get('percentile'); x=selection.percent/100
        if selection.tail!='all' and (p is None or not ((selection.tail in ('top','both') and p>=1-x) or (selection.tail in ('bottom','both') and p<=x))):
            continue
        rows.append(row)
    present=[r for r in rows if r.get(selection.sort) is not None]
    missing=[r for r in rows if r.get(selection.sort) is None]
    present.sort(key=lambda r:r['symbol'])
    present.sort(key=lambda r:r[selection.sort],reverse=selection.direction=='desc')
    return present+sorted(missing,key=lambda r:r['symbol'])


def csv_export(result, selection=None):
    rows=result['combined'] if selection is None else select_rows(result,selection)
    fields=(*FIELDS,'ota_raw_status',*('ota_raw.'+field for field in result.get('ota_raw_fields',())),*EXTRA_FIELDS,*TRADIER_FIELDS)
    stream=io.StringIO(newline='')
    writer=csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
    writer.writeheader()
    writer.writerows({k:csv_cell(v) for k,v in row.items()} for row in rows)
    return stream.getvalue().encode('utf-8-sig')


def coverage(result):
    rows=result['combined']
    return {'master_symbols':len(rows),'ranked':len(result['ranked']),'excluded':len(result['excluded']),
            'matched':result['ota_join_counts']['matched'],
            'tradier_matched':sum(r['tradier_status']=='supplied_freshness_unverified' for r in rows),
            'symbols_failed':sum(r['tradier_status']=='failed' for r in rows)}


class ReportService:
    def __init__(self,catalog):
        self.catalog=catalog

    def demo_sources(self):
        from .demo import make_snapshot
        from .dashboard import synthetic_ota
        snapshot=make_snapshot();ota=synthetic_ota(snapshot)
        ota.update(schema_version=2,representation='ota_raw',acquisition_status='completed_short_page')
        ota['rows']=[{'symbol':r['symbol'],'values':{k:v for k,v in r.items() if k!='symbol'}} for r in ota['rows']]
        prices=self.catalog.publish(encoded(snapshot),kind='prices',profile='synthetic',master=snapshot['universe'],observed_at=snapshot['membership_observed_at'])
        source=self.catalog.publish(encoded(ota),kind='ota',profile='synthetic',observed_at=ota['retrieved_at'])
        return prices,source

    def generate(self,prices_id,ota_id=None,tradier_id=None,*,now=None):
        from .progress import RunProgress
        from .run_ids import new_run_id
        from .scan_service import code_revision
        from .dashboard import atomic_json
        ids=[aid for aid in (prices_id,ota_id,tradier_id) if aid]
        if len(set(ids))!=len(ids):
            raise DataError('REPORT_SOURCE_INVALID')
        snapshot=json.loads(self.catalog.read(prices_id,'prices'),object_pairs_hook=pairs)
        ota=json.loads(self.catalog.read(ota_id,'ota'),object_pairs_hook=pairs) if ota_id else None
        probes=[json.loads(self.catalog.read(tradier_id,'tradier'),object_pairs_hook=pairs)] if tradier_id else []
        if snapshot.get('profile') not in ('synthetic','public'):
            raise DataError('REPORT_SOURCE_INVALID')
        progress=RunProgress(self.catalog.root/'artifacts/logs',new_run_id(),'web-report',snapshot['profile'],code_revision())
        code, counts='REPORT_FAILED',{}
        try:
            progress.begin();progress.start('dashboard')
            result=compose_report(snapshot,ota,probes=probes,now=now)
            result['source_artifact_ids']={'prices':prices_id,'ota':ota_id,'tradier':tradier_id}
            result['source_metadata']={'price_session':snapshot['as_of'],
                                       'membership_observed_at':snapshot.get('membership_observed_at'),
                                       'ota_retrieved_at':ota.get('retrieved_at') if ota else None,
                                       'tradier_started_at':probes[0].get('started_at') if probes else None,
                                       'tradier_profile':probes[0].get('profile') if probes else None}
            counts=coverage(result)
            progress.finish(counts=counts);progress.start('reports')
            aid=self.catalog.publish(encoded(result),kind='report',profile=result['profile'],
                                     input_ids=ids,run_id=progress.run_id,master=snapshot['universe'],
                                     observed_at=snapshot.get('membership_observed_at'),settings=result['filters'],
                                     state='partial' if counts['symbols_failed'] else 'succeeded')
            progress.finish();code=None
            print(f'Saved report: {self.catalog.root / self.catalog.record(aid)["relative_path"]}')
            return aid
        finally:
            progress.end(code,counts=counts)
            progress.close()
            path=self.catalog.root/'artifacts/agent-review'/f'{progress.run_id}.json'
            atomic_json(path,{'schema_version':1,'run_id':progress.run_id,'code_revision':code_revision(),
                             'profile':snapshot['profile'],'checks':[{'name':'web_report','status':'failed' if code else 'passed'}],
                             'counts':counts,'error_code':code})
            print(f'Agent review: {path}')

    def load(self,artifact_id):
        return json.loads(self.catalog.read(artifact_id,'report'),object_pairs_hook=pairs)
