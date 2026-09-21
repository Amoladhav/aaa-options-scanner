"""Shared saved-data composition, selection and exports for CLI and local web."""
import csv
from datetime import datetime, timezone
import io
import json

from .catalog import encoded
from .core import DataError
from .dashboard import combine, attach_tradier, FILTER_DEFAULTS, EXTRA_FIELDS, TRADIER_FIELDS
from .ota_config import pairs
from .report import FIELDS, csv_cell
from .report_selection import Selection, select_rows, watchlist_export, report_columns

_AUTO_PRIOR = object()


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

    def generate(self,prices_id,ota_id=None,tradier_id=None,*,now=None,filters=None,
                 prior_id=_AUTO_PRIOR,replay_of=None,tradier_extra=()):
        from .progress import RunProgress
        from .run_ids import new_run_id
        from .scan_service import code_revision
        from .dashboard import atomic_json
        tradier_ids=[aid for aid in (tradier_id,*tradier_extra) if aid]
        ids=[aid for aid in (prices_id,ota_id,*tradier_ids) if aid]
        if len(set(ids))!=len(ids):
            raise DataError('REPORT_SOURCE_INVALID')
        snapshot=json.loads(self.catalog.read(prices_id,'prices'),object_pairs_hook=pairs)
        ota=json.loads(self.catalog.read(ota_id,'ota'),object_pairs_hook=pairs) if ota_id else None
        probes=[json.loads(self.catalog.read(aid,'tradier'),object_pairs_hook=pairs) for aid in tradier_ids]
        if snapshot.get('profile') not in ('synthetic','public'):
            raise DataError('REPORT_SOURCE_INVALID')
        from .crs_history import CRSHistory
        from .core import CALCULATION_VERSION
        history=CRSHistory(self.catalog)
        if prior_id is _AUTO_PRIOR:
            prior_id=history.prior(snapshot)
        previous=history.previous(prior_id,snapshot)
        legacy_prior=prior_id if prior_id and self.catalog.record(prior_id)['kind']=='legacy_history' else None
        ids.extend(aid for aid in (prior_id,replay_of) if aid and aid not in ids)
        evaluation_time=now or datetime.now(timezone.utc)
        progress=RunProgress(self.catalog.root/'artifacts/logs',new_run_id(),'web-report',snapshot['profile'],code_revision())
        code, counts='REPORT_FAILED',{}
        try:
            progress.begin();progress.start('dashboard')
            result=compose_report(snapshot,ota,probes=probes,now=evaluation_time,
                                  filters=filters,previous=previous)
            result['history_provenance']={'schema_version':1,'calculation_version':CALCULATION_VERSION,
                                          'prior_artifact_id':None if legacy_prior else prior_id,'replay_of':replay_of}
            if legacy_prior:
                result['history_provenance'].update(legacy_prior_artifact_id=legacy_prior,
                                                    legacy_limitations='Full master, inputs and code version unavailable',
                                                    master_changed=None)
            elif prior_id:
                prior_master=history.show(prior_id)['run']['master_id']
                result['history_provenance']['master_changed']=prior_master != result['master_id']
            else:
                result['history_provenance']['master_changed']=False
            result['source_artifact_ids']={'prices':prices_id,'ota':ota_id,'tradier':tradier_id}
            if tradier_extra:
                result['source_artifact_ids']['tradier_extra']=list(tradier_extra)
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
                                     state='partial' if counts['symbols_failed'] else 'succeeded',history=result)
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

    def replay(self,artifact_id):
        """Pin inputs, evaluation clock, candidate settings and prior history.

        Different software must be an explicit reprocessing operation, not a
        claim of exact replay. Browser presentation filters are not persisted.
        """
        from .crs_history import CRSHistory
        from .scan_service import code_revision
        recorded=CRSHistory(self.catalog).show(artifact_id)['run']
        if recorded['code_revision'] != code_revision():
            raise DataError('HISTORY_REPLAY_VERSION_MISMATCH')
        original=self.load(artifact_id)
        ids=original['source_artifact_ids']
        return self.generate(ids['prices'],ids['ota'],ids['tradier'],
                             now=datetime.fromisoformat(original['generated_at']),
                             filters=original['filters'],prior_id=recorded['prior_artifact_id'] or original['history_provenance'].get('legacy_prior_artifact_id'),
                             replay_of=artifact_id,tradier_extra=ids.get('tradier_extra',()))

    def generate_from_payloads(self,snapshot,ota,*,probes=(),filters=None,now=None):
        """CLI saved-file adapter: capture validated inputs, then use the same builder.

        Decoded inputs are serialized, not claimed as original transport bytes.
        Original CLI input/output files remain outside this immutable catalog copy.
        """
        # Validate all joins before registering source artifacts.
        compose_report(snapshot,ota,probes=probes,filters=filters,now=now)
        prices=self.catalog.publish(encoded(snapshot),kind='prices',profile=snapshot['profile'],
                                    master=snapshot['universe'],observed_at=snapshot['membership_observed_at'])
        source=self.catalog.publish(encoded(ota),kind='ota',profile='synthetic' if snapshot['profile']=='synthetic' else 'ota',
                                    observed_at=ota['retrieved_at']) if ota is not None else None
        quotes=[self.catalog.publish(encoded(probe),kind='tradier',profile=probe['profile'],
                                     observed_at=probe.get('started_at',probe.get('retrieved_at'))) for probe in probes]
        return self.generate(prices,source,quotes[0] if quotes else None,
                             tradier_extra=quotes[1:],filters=filters,now=now)
