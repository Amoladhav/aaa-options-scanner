"""Durable work tested against synthetic catalogs and denied live access."""
from contextlib import redirect_stdout
import io,json,sqlite3,unittest
from unittest.mock import patch
from offline_boundary import temp
from throttle_fixtures import virtual_throttle_time
from trading_scanner.catalog import Catalog
from trading_scanner.core import DataError
from trading_scanner.jobs import Jobs
from trading_scanner.report_service import ReportService
from trading_scanner.recovery import RecoveryService
from trading_scanner.ota_config import parse_config
from trading_scanner.cli import main

CRITERIA=[{'field':'optionable','valueFilter':'BOOLEAN','valueChoices':'Yes','criteria':'true'}]

class JobTests(unittest.TestCase):
    def setUp(self):
        self.root=temp/self._testMethodName;self.catalog=Catalog(self.root);self.catalog.initialize()
        self.jobs=Jobs(self.catalog);self.service=ReportService(self.catalog)
        self.prices,self.ota=self.service.demo_sources()
        self.enterContext(redirect_stdout(io.StringIO()))
        self.enterContext(virtual_throttle_time())

    def submit(self,key='a'*32):return self.jobs.submit_report(key,self.prices,self.ota)

    def test_idempotency_pins_request_and_history(self):
        job=self.submit();self.service.generate(self.prices,self.ota)
        self.assertEqual(self.submit(),job)
        self.assertIsNone(self.jobs.get(job)['request']['prior'])
        with self.assertRaisesRegex(DataError,'JOB_CONFLICT'):
            self.jobs.submit_report('a'*32,self.prices)
        with self.catalog.connection() as db:
            with self.assertRaises(sqlite3.IntegrityError):db.execute('UPDATE durable_jobs SET request_json=?',('{}',))
        self.assertEqual(len(self.jobs.list()),1)

    def test_report_worker_records_output_and_safe_events(self):
        job=self.submit();row=self.jobs.run(job)
        self.assertEqual(row['state'],'succeeded',row)
        report=self.service.load(row['output_artifact_id'])
        self.assertEqual(report['source_artifact_ids']['prices'],self.prices)
        self.assertEqual(len(report['combined']),len(json.loads(self.catalog.read(self.prices))['universe']))
        self.assertGreater(len(self.jobs.events(job)),3)
        with self.assertRaisesRegex(DataError,'JOB_STATE_INVALID'):self.jobs.run(job)

    def test_single_claim_cancel_and_terminal_no_rerun(self):
        first=self.submit();second=self.submit('b'*32);worker=self.jobs.claim(first)
        other=Jobs(Catalog(self.root))
        with self.assertRaisesRegex(DataError,'JOB_BUSY'):other.claim(second)
        self.assertEqual(other.cancel(first),'cancel_requested')
        with self.assertRaises(KeyboardInterrupt):self.jobs.check(first,worker)
        self.jobs.finish(first,worker,'cancelled',error='RUN_CANCELLED')
        self.assertEqual(other.cancel(second),'cancelled')
        with self.assertRaisesRegex(DataError,'JOB_STATE_INVALID'):other.claim(second)

    def test_recovery_requires_stopped_confirmation_and_fences_worker(self):
        job=self.submit();worker=self.jobs.claim(job)
        with self.assertRaisesRegex(DataError,'JOB_CONFIRM_STOPPED'):self.jobs.recover(job)
        self.jobs.recover(job,confirmed_stopped=True)
        for call in (lambda:self.jobs.check(job,worker),lambda:self.jobs.finish(job,worker,'succeeded')):
            with self.assertRaisesRegex(DataError,'JOB_LEASE_LOST'):call()
        self.assertEqual(self.jobs.get(job)['state'],'interrupted')

    def test_exception_sanitized_and_cooperative_cancel(self):
        job=self.submit()
        def fail(row,check):raise RuntimeError('private-marker')
        self.assertEqual(self.jobs.run(job,executor=fail)['error_code'],'JOB_FAILED')
        self.assertNotIn('private-marker',json.dumps(self.jobs.events(job)))
        job=self.submit('b'*32)
        def cancel(row,check):self.jobs.cancel(row['id']);check()
        self.assertEqual(self.jobs.run(job,executor=cancel)['state'],'cancelled')

    def test_version_change_requires_new_submission(self):
        job=self.submit()
        with patch('trading_scanner.jobs.code_revision',return_value='changed'):
            with self.assertRaisesRegex(DataError,'JOB_VERSION_MISMATCH'):self.jobs.run(job)
        self.assertEqual(self.jobs.get(job)['state'],'queued')

    def test_backup_preserves_states_without_worker_start(self):
        queued=self.submit();active=self.submit('b'*32);self.jobs.claim(active)
        backup=temp/(self._testMethodName+'-backup');target=temp/(self._testMethodName+'-restore')
        recovery=RecoveryService(self.root);recovery.backup(backup);recovery.restore(backup,target)
        jobs=Jobs(Catalog(target))
        self.assertEqual(jobs.get(queued)['state'],'queued');self.assertEqual(jobs.get(active)['state'],'running')
        with self.assertRaisesRegex(DataError,'JOB_BUSY'):jobs.claim(queued)

    def test_ota_submission_does_not_resolve_credentials_and_synthetic_execution(self):
        config=parse_config(json.dumps(CRITERIA))
        with patch('trading_scanner.credentials.resolve',return_value='synthetic-local-input') as resolve:
            job=self.jobs.submit_ota('a'*32,config,credential_source='env')
            resolve.assert_not_called()
            config['criteria'].clear()
            with patch('trading_scanner.ota_fetch.fetch_page',return_value=[]):row=self.jobs.run(job)
            self.assertEqual(row['state'],'succeeded',row)
            self.assertFalse(resolve.call_args.kwargs['allow_prompt'])
        self.assertEqual(self.catalog.record(row['output_artifact_id'])['kind'],'ota')
        self.assertEqual(len(row['request']['config']['criteria']),1)

    def test_cli_submission_run_show_and_cancellation(self):
        self.assertEqual(main(['job-submit-report','--prices',self.prices,'--action-key','a'*32],self.root),0)
        job=self.jobs.list()[0]['id']
        self.assertEqual(main(['job-run','--job',job],self.root),0)
        self.assertEqual(main(['job-show','--job',job],self.root),0)
        self.assertEqual(main(['job-list'],self.root),0)
        self.assertEqual(self.jobs.get(job)['state'],'succeeded')

    def test_ota_cancel_between_pages_keeps_incomplete_capture_unindexed(self):
        config=parse_config(json.dumps(CRITERIA));job=self.jobs.submit_ota('a'*32,config,page_size=1)
        def page(*args,**kwargs):
            self.jobs.cancel(job)
            return [{'symbol':'AAA','values':{}}]
        with patch('trading_scanner.credentials.resolve',return_value='synthetic-local-input'),patch('trading_scanner.ota_fetch.fetch_page',side_effect=page) as fetch:
            row=self.jobs.run(job)
        self.assertEqual(row['state'],'cancelled',row);self.assertIsNone(row['output_artifact_id'])
        fetch.assert_called_once()
        self.assertFalse((self.root/'artifacts/ota'/row['run_id']/'results.json').exists())

    def test_tradier_pinned_master_partial_output_and_explicit_profile(self):
        from trading_scanner.catalog import encoded
        from trading_scanner.demo import make_snapshot
        snapshot=make_snapshot();snapshot['profile']='public'
        snapshot['universe']=[{'symbol':s,'group':'stock'} for s in ('AAA','CCC')]
        prices=self.catalog.publish(encoded(snapshot),kind='prices',profile='public')
        with patch('trading_scanner.credentials.resolve',return_value='synthetic-local-input') as resolve:
            job=self.jobs.submit_tradier('a'*32,prices,'production','2026-09-19')
            resolve.assert_not_called()
            with self.assertRaisesRegex(DataError,'JOB_CONFLICT'):
                self.jobs.submit_tradier('a'*32,prices,'sandbox','2026-09-19')
            def probe(profile,symbol,credential,**kwargs):
                kwargs['before_request']('quote')
                if symbol=='CCC':raise DataError('TRADIER_NO_ATM_PAIR')
                return {'schema_version':1,'source':'tradier','profile':profile,'symbol':symbol,
                        'retrieved_at':'2026-09-19T22:00:00+00:00','atm_strike':100,'expiration':'2026-10-16',
                        'expiration_type':'standard','call':{'strike':100},'put':{'strike':100}}
            with patch('trading_scanner.tradier_batch.fetch_probe',side_effect=probe) as fetch:row=self.jobs.run(job)
        self.assertEqual(row['state'],'partial',row);self.assertEqual(fetch.call_count,2)
        batch=json.loads(self.catalog.read(row['output_artifact_id']))
        self.assertEqual([r['symbol'] for r in batch['rows']],['AAA','CCC'])
        self.assertEqual(batch['status'],'completed_with_errors')
        self.assertFalse(resolve.call_args.kwargs['allow_prompt'])

    def test_governor_cancellation_during_wait_never_calls_transport(self):
        from trading_scanner.throttling import Governor
        job=self.submit();worker=self.jobs.claim(job);calls=[]
        def sleep(seconds):self.jobs.cancel(job)
        with Governor(self.root/'artifacts/throttling','ota',sleep=sleep,
                      cancel_check=lambda:self.jobs.check(job,worker)) as governor:
            with self.assertRaises(KeyboardInterrupt):governor.call(lambda:calls.append('transport'))
        self.assertEqual(calls,[])
        self.jobs.finish(job,worker,'cancelled',error='RUN_CANCELLED')

    def test_event_privacy_rejects_unknown_counts_and_errors(self):
        job=self.submit();worker=self.jobs.claim(job)
        event={'stage':'job_run','completed':0,'total':1,'counts':{'private-marker':1},'error_code':None}
        with self.assertRaisesRegex(DataError,'JOB_INVALID'):self.jobs.observe(job,worker,event)
        event.update(counts={},error_code='private-marker')
        with self.assertRaisesRegex(DataError,'JOB_INVALID'):self.jobs.observe(job,worker,event)
        self.assertNotIn('private-marker',json.dumps(self.jobs.events(job)))
