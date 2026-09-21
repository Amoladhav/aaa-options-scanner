"""Explicit one-worker durable jobs. Submission never executes work."""
from datetime import datetime,timezone
import json
import uuid

from .catalog import encoded,digest,identifier
from .core import DataError
from .dashboard import FILTER_DEFAULTS,filters_checked
from .ota_config import pairs
from .report_service import ReportService
from .crs_history import CRSHistory
from .progress import SAFE_ERRORS,COUNT_KEYS,STAGES
from .run_ids import new_run_id
from .scan_service import code_revision

ACTIVE=('running','cancel_requested')
TERMINAL=('succeeded','partial','failed','cancelled','interrupted')


def stamp():return datetime.now(timezone.utc).isoformat()


class Jobs:
    def __init__(self,catalog):self.catalog=catalog

    def submit_report(self,action_key,prices,ota=None,tradier=None,*,filters=None):
        identifier(action_key)
        snapshot=json.loads(self.catalog.read(prices,'prices'),object_pairs_hook=pairs)
        if snapshot.get('profile') not in ('synthetic','public'):raise DataError('JOB_INVALID')
        if ota:self.catalog.read(ota,'ota')
        if tradier:self.catalog.read(tradier,'tradier')
        request={'prices':prices,'ota':ota,'tradier':tradier,
                 'filters':filters_checked(FILTER_DEFAULTS if filters is None else filters)}
        # Resolve prior once on first submission. An identical retried action
        # returns its first job, even if canonical history changed meanwhile.
        existing=self._existing(action_key)
        if existing:
            old=json.loads(existing['request_json'])
            if existing['kind']!='report-build' or any(old.get(k)!=v for k,v in request.items()):raise DataError('JOB_CONFLICT')
            return existing['id']
        prior=CRSHistory(self.catalog).prior(snapshot)
        request['prior']=prior
        request['evaluation_time']=stamp()
        return self._submit(action_key,'report-build',snapshot['profile'],request,[v for v in (prices,ota,tradier,prior) if v])

    def submit_ota(self,action_key,config,*,page_size=600,max_pages=50,credential_source='env'):
        from .ota_config import parse_config
        from .ota_fetch import request_path
        request_path(1,page_size)
        if type(max_pages) is not int or not 1<=max_pages<=100 or credential_source not in ('env','store'):
            raise DataError('JOB_INVALID')
        checked=parse_config(json.dumps(config['criteria'],allow_nan=False))
        if checked!=config:raise DataError('JOB_INVALID')
        return self._submit(action_key,'ota-fetch','ota',{'config':checked,'page_size':page_size,
                             'max_pages':max_pages,'credential_source':credential_source},[])

    def submit_tradier(self,action_key,prices,profile,as_of,*,credential_source='env'):
        from .tradier import observation_date
        from .tradier_batch import master_universe
        if profile not in ('sandbox','production') or credential_source not in ('env','store') or not isinstance(as_of,str):
            raise DataError('JOB_INVALID')
        snapshot=json.loads(self.catalog.read(prices,'prices'),object_pairs_hook=pairs)
        master_universe(snapshot)
        selected_date=observation_date(as_of).isoformat()
        return self._submit(action_key,'tradier-fetch',profile,{'prices':prices,'as_of':selected_date,
                              'credential_source':credential_source},[prices])

    def observe(self,job,worker,event):
        with self.catalog.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state,worker_id FROM durable_jobs WHERE id=?',(job,)).fetchone()
            if row is None or row['worker_id']!=worker or row['state'] not in ACTIVE:raise DataError('JOB_LEASE_LOST')
            self._event(db,job,row['state'],stage=event['stage'],completed=event['completed'],total=event['total'],
                        counts=event['counts'],error=event['error_code'])
            db.commit()

    def _provider(self,row,worker):
        from argparse import Namespace
        from .catalog_service import index_source
        request=row['request'];check=lambda:self.check(row['id'],worker)
        observer=lambda event:self.observe(row['id'],worker,event)
        if row['kind']=='ota-fetch':
            from .ota_fetch import run_fetch
            status=run_fetch(self.catalog.root,page_size=request['page_size'],max_pages=request['max_pages'],
                             credential_source=request['credential_source'],config_override=request['config'],
                             cancel_check=check,run_id=row['run_id'],observer=observer)
            path=self.catalog.root/'artifacts/ota'/row['run_id']/'results.json';kind='ota'
        else:
            from .tradier_batch import run_batch
            snapshot=json.loads(self.catalog.read(request['prices'],'prices'),object_pairs_hook=pairs)
            args=Namespace(profile=row['profile'],as_of=request['as_of'],credential_source=request['credential_source'])
            status=run_batch(self.catalog.root,args,snapshot_override=snapshot,cancel_check=check,run_id=row['run_id'],observer=observer)
            path=self.catalog.root/'artifacts/tradier'/row['profile']/row['run_id']/'batch.json';kind='tradier'
        review_path=self.catalog.root/'artifacts/agent-review'/(row['run_id']+'.json')
        with review_path.open('rb') as stream:data=stream.read(65537)
        if len(data)>65536:raise DataError('JOB_FAILED')
        review=json.loads(data,object_pairs_hook=pairs)
        error=review.get('error_code')
        if error is not None and error not in SAFE_ERRORS:raise DataError('JOB_FAILED')
        if status==130:return 'cancelled',None,'RUN_CANCELLED'
        if status==0 and error is None:return 'succeeded',index_source(self.catalog,path,kind),None
        if status==1 and error=='TRADIER_BATCH_PARTIAL':return 'partial',index_source(self.catalog,path,kind),error
        return 'failed',None,error or 'JOB_FAILED'

    def _existing(self,action_key):
        with self.catalog.connection() as db:
            row=db.execute('SELECT * FROM durable_jobs WHERE action_key=?',(action_key,)).fetchone()
        return dict(row) if row else None

    def _submit(self,action_key,kind,profile,request,inputs):
        identifier(action_key)
        data=encoded(request);job=uuid.uuid4().hex
        if len(data)>131072:raise DataError('JOB_INVALID')
        with self.catalog.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            previous=db.execute('SELECT id,request_hash,kind,profile,request_json FROM durable_jobs WHERE action_key=?',(action_key,)).fetchone()
            if previous:
                same=previous['request_hash']==digest(data)
                if kind=='report-build':
                    old=json.loads(previous['request_json'])
                    same=all(old.get(k)==v for k,v in request.items() if k not in ('prior','evaluation_time'))
                if not same or previous['kind']!=kind or previous['profile']!=profile:raise DataError('JOB_CONFLICT')
                return previous['id']
            db.execute('INSERT INTO durable_jobs VALUES (?,?,?,?,?,?,?,?,?,NULL,?,NULL,NULL,NULL,NULL)',
                       (job,action_key,kind,profile,data.decode(),digest(data),code_revision(),new_run_id(),'queued',stamp()))
            for aid in set(inputs):db.execute('INSERT INTO job_inputs VALUES (?,?)',(job,aid))
            self._event(db,job,'queued');db.commit()
        return job

    def _event(self,db,job,state,*,stage='job_run',completed=0,total=1,counts=None,error=None):
        counts={} if counts is None else counts
        if (stage not in STAGES or type(completed) is not int or completed<0
                or total is not None and (type(total) is not int or total<completed)
                or any(k not in COUNT_KEYS or type(v) is not int or v<0 for k,v in counts.items())
                or error is not None and error not in SAFE_ERRORS):raise DataError('JOB_INVALID')
        db.execute('INSERT INTO job_events(job_id,created_at,state,stage,completed,total,counts_json,error_code) VALUES (?,?,?,?,?,?,?,?)',
                   (job,stamp(),state,stage,completed,total,encoded(counts).decode(),error))

    def get(self,job):
        identifier(job)
        with self.catalog.connection() as db:
            row=db.execute('SELECT * FROM durable_jobs WHERE id=?',(job,)).fetchone()
        if row is None:raise DataError('JOB_NOT_FOUND')
        row=dict(row)
        if digest(row['request_json'].encode())!=row['request_hash']:raise DataError('JOB_INVALID')
        row['request']=json.loads(row.pop('request_json'),object_pairs_hook=pairs)
        return row

    def list(self):
        with self.catalog.connection() as db:
            return [dict(r) for r in db.execute('SELECT id,kind,profile,state,created_at,started_at,finished_at,error_code,output_artifact_id FROM durable_jobs ORDER BY rowid DESC LIMIT 1000')]

    def events(self,job):
        self.get(job)
        with self.catalog.connection() as db:
            return [dict(r) for r in db.execute('SELECT * FROM job_events WHERE job_id=? ORDER BY sequence DESC LIMIT 100',(job,))]

    def cancel(self,job):
        identifier(job)
        with self.catalog.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state FROM durable_jobs WHERE id=?',(job,)).fetchone()
            if row is None:raise DataError('JOB_NOT_FOUND')
            state=row['state']
            if state=='queued':state='cancelled'
            elif state=='running':state='cancel_requested'
            else:return state
            db.execute('UPDATE durable_jobs SET state=?,finished_at=? WHERE id=?',(state,stamp() if state=='cancelled' else None,job))
            self._event(db,job,state);db.commit()
        return state

    def recover(self,job,*,confirmed_stopped=False):
        if confirmed_stopped is not True:raise DataError('JOB_CONFIRM_STOPPED')
        identifier(job)
        with self.catalog.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state FROM durable_jobs WHERE id=?',(job,)).fetchone()
            if row is None:raise DataError('JOB_NOT_FOUND')
            if row['state'] not in ACTIVE:raise DataError('JOB_STATE_INVALID')
            db.execute("UPDATE durable_jobs SET state='interrupted',finished_at=?,error_code='JOB_INTERRUPTED' WHERE id=?",(stamp(),job))
            self._event(db,job,'interrupted',error='JOB_INTERRUPTED');db.commit()

    def claim(self,job):
        current=self.get(job)
        if current['code_revision']!=code_revision():raise DataError('JOB_VERSION_MISMATCH')
        worker=uuid.uuid4().hex
        with self.catalog.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM durable_jobs WHERE state IN ('running','cancel_requested')").fetchone():raise DataError('JOB_BUSY')
            changed=db.execute("UPDATE durable_jobs SET state='running',worker_id=?,started_at=? WHERE id=? AND state='queued'",(worker,stamp(),job)).rowcount
            if changed!=1:raise DataError('JOB_STATE_INVALID')
            self._event(db,job,'running');db.commit()
        return worker

    def check(self,job,worker):
        row=self.get(job)
        if row['worker_id']!=worker or row['state'] not in ACTIVE:raise DataError('JOB_LEASE_LOST')
        if row['state']=='cancel_requested':raise KeyboardInterrupt()

    def finish(self,job,worker,state,*,output=None,error=None):
        if state not in TERMINAL:raise DataError('JOB_INVALID')
        with self.catalog.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT state,worker_id FROM durable_jobs WHERE id=?',(job,)).fetchone()
            if row is None or row['worker_id']!=worker or row['state'] not in ACTIVE:raise DataError('JOB_LEASE_LOST')
            # Completed publication wins a cancellation that arrived after the
            # last checkpoint. Do not mislabel already durable output as undone.
            db.execute('UPDATE durable_jobs SET state=?,finished_at=?,error_code=?,output_artifact_id=? WHERE id=?',(state,stamp(),error,output,job))
            self._event(db,job,state,completed=int(state=='succeeded'),error=error);db.commit()

    def run(self,job,*,executor=None):
        worker=self.claim(job);row=self.get(job)
        try:
            self.check(job,worker)
            if executor:
                output=executor(row,lambda:self.check(job,worker))
            elif row['kind']=='report-build':
                request=row['request']
                output=ReportService(self.catalog).generate(request['prices'],request['ota'],request['tradier'],
                           filters=request['filters'],prior_id=request['prior'],now=datetime.fromisoformat(request['evaluation_time']),run_id=row['run_id'],
                           cancel_check=lambda:self.check(job,worker),observer=lambda event:self.observe(job,worker,event))
            elif row['kind'] in ('ota-fetch','tradier-fetch'):
                state,output,error=self._provider(row,worker)
                self.finish(job,worker,state,output=output,error=error)
                return self.get(job)
            else:raise DataError('JOB_INVALID')
            state='succeeded';error=None
            if output:
                with self.catalog.connection() as db:
                    published=db.execute('SELECT r.state FROM artifacts a JOIN runs r ON r.id=a.run_id WHERE a.id=?',(output,)).fetchone()
                if published and published['state']=='partial':state='partial';error='TRADIER_BATCH_PARTIAL'
            self.finish(job,worker,state,output=output,error=error)
        except KeyboardInterrupt:
            self.finish(job,worker,'cancelled',error='RUN_CANCELLED')
        except Exception as exc:
            error=exc.args[0] if isinstance(exc,DataError) and len(exc.args)==1 and exc.args[0] in SAFE_ERRORS else 'JOB_FAILED'
            self.finish(job,worker,'failed',error=error)
        return self.get(job)
