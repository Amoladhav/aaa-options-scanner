"""Synthetic personal scheduling, transactional claims and DST semantics."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone, tzinfo
import io
import json
import unittest
from unittest.mock import patch
from offline_boundary import temp
from trading_scanner.core import DataError
from trading_scanner.scheduling import ScheduleService, occurrence, validate


class Pacific2026(tzinfo):
    """Synthetic single-year DST fixture, independent of OS timezone files."""
    def utcoffset(self, dt):
        local = dt.replace(tzinfo=None)
        spring, autumn = datetime(2026,3,8,2), datetime(2026,11,1,2)
        daylight = spring + timedelta(hours=1) <= local < autumn
        if datetime(2026,11,1,1) <= local < autumn:
            daylight = not dt.fold
        return timedelta(hours=-7 if daylight else -8)
    def dst(self, dt):
        return self.utcoffset(dt) + timedelta(hours=8)
    def fromutc(self, dt):
        utc = dt.replace(tzinfo=None)
        daylight = datetime(2026,3,8,10) <= utc < datetime(2026,11,1,9)
        local = utc + timedelta(hours=-7 if daylight else -8)
        fold = int(datetime(2026,11,1,9) <= utc < datetime(2026,11,1,10))
        return local.replace(tzinfo=self, fold=fold)


class SchedulingTests(unittest.TestCase):
    def setUp(self):
        self.root = temp / self._testMethodName
        self.service = ScheduleService(self.root)
        self.settings = {'schema_version':1,'time':'05:00','timezone':'UTC','task':'ota','enabled':True,'grace_minutes':60}
        self.now = datetime(2026,9,20,5,tzinfo=timezone.utc)

    def test_disabled_configuration_and_future_time_never_dispatch(self):
        self.service.configure({**self.settings,'enabled':False})
        self.assertIsNone(self.service.tick(self.now, lambda job:self.fail('disabled dispatch')))
        self.service.set_enabled(True)
        self.assertIsNone(self.service.claim(self.now - timedelta(seconds=1)))
        self.assertEqual(self.service.view(self.now)['next_due_local'], self.now.isoformat())

    def test_once_per_local_day_survives_restart_and_edits(self):
        self.service.configure(self.settings)
        jobs = []
        result = self.service.tick(self.now, lambda job: jobs.append(job) or 0, wall=lambda:self.now, monotonic=lambda:1)
        self.assertEqual(result['status'], 'succeeded')
        self.service.configure({**self.settings,'time':'06:00'})
        restarted = ScheduleService(self.root)
        self.assertIsNone(restarted.claim(self.now + timedelta(hours=1)))
        self.assertEqual(len(jobs),1)
        self.assertEqual(restarted.view(self.now)['recent_jobs'][0]['elapsed_seconds'],0)
        self.assertIsNotNone(restarted.claim(self.now + timedelta(days=1,hours=1)))

    def test_two_services_cannot_claim_the_same_job_and_crash_blocks_future_days(self):
        self.service.configure(self.settings)
        self.assertIsNotNone(self.service.claim(self.now))
        other = ScheduleService(self.root)
        for stamp in (self.now,self.now+timedelta(days=1)):
            with self.assertRaisesRegex(DataError,'SCHEDULE_BUSY'):
                other.claim(stamp)
        self.assertTrue(other.view(self.now)['blocked_by_running_job'])
        other.acknowledge_stopped('2026-09-20')
        self.assertIsNone(other.claim(self.now))
        self.assertIsNotNone(other.claim(self.now+timedelta(days=1)))

    def test_late_runs_are_missed_without_replay(self):
        self.service.configure(self.settings)
        self.assertIsNone(self.service.claim(self.now+timedelta(hours=2)))
        self.assertEqual(self.service.view(self.now)['recent_jobs'][0]['status'],'missed')
        self.assertIsNone(self.service.claim(self.now))
        self.assertIsNotNone(self.service.claim(self.now+timedelta(days=1)))

    def test_failure_and_cancel_are_terminal_not_retried(self):
        self.service.configure(self.settings)
        def failure(job):
            raise RuntimeError('synthetic-private-exception')
        with self.assertRaises(RuntimeError):
            self.service.tick(self.now,failure,wall=lambda:self.now)
        self.assertEqual(self.service.view(self.now)['recent_jobs'][0]['error_code'],'SCHEDULE_TASK_FAILED')
        self.assertNotIn('synthetic-private-exception', json.dumps(self.service.view(self.now)))
        def cancel(job):
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.service.tick(self.now+timedelta(days=1),cancel,wall=lambda:self.now+timedelta(days=1))
        self.assertEqual(self.service.view(self.now)['recent_jobs'][0]['status'],'cancelled')
        self.assertIsNone(self.service.claim(self.now+timedelta(days=1)))

    def test_personal_settings_are_strict_and_no_shell_task_is_accepted(self):
        for changes in ({'time':'25:00'},{'task':'shell'},{'enabled':'true'},{'timezone':'../private'}, {'grace_minutes':0}, {'unexpected':'synthetic'}):
            with self.assertRaises((DataError,ValueError)):
                validate({**self.settings,**changes}, lambda name:timezone.utc)
        with self.assertRaisesRegex(DataError,'SCHEDULE_INVALID'):
            self.service.claim(datetime(2026,9,20,5))

    def test_dst_gap_skips_fold_uses_first_and_5am_tracks_local_clock(self):
        resolve = lambda name:Pacific2026()
        settings = {**self.settings,'timezone':'America/Los_Angeles'}
        spring = datetime(2026,3,8).date()
        autumn = datetime(2026,11,1).date()
        self.assertIsNone(occurrence(spring,{**settings,'time':'02:30'},resolve))
        self.assertEqual(occurrence(autumn,{**settings,'time':'01:30'},resolve),datetime(2026,11,1,8,30,tzinfo=timezone.utc))
        self.assertEqual(occurrence(spring,settings,resolve).hour,12)
        self.assertEqual(occurrence(autumn,settings,resolve).hour,13)

    def test_cli_settings_and_idle_worker_do_not_call_providers(self):
        from trading_scanner.cli import main
        with redirect_stdout(io.StringIO()), patch('trading_scanner.schedule_cli.execute_job') as execute:
            self.assertEqual(main(['schedule','set','--time','05:00','--timezone','UTC'],self.root),0)
            self.assertEqual(main(['schedule-worker','--once'],self.root),0)
            self.assertEqual(main(['schedule','enable'],self.root),0)
            self.assertEqual(main(['schedule','disable'],self.root),0)
            execute.assert_not_called()

    def test_dispatch_uses_stored_credentials_and_services_not_cli(self):
        from trading_scanner.schedule_cli import execute_job
        from trading_scanner.cli import main
        self.service.configure(self.settings)
        for task in ('ota','daily'):
            job={'id':('a' if task=='ota' else 'b')*32,'settings':{**self.settings,'task':task}}
            with patch('trading_scanner.cli.main',side_effect=AssertionError('recursive CLI')), patch('trading_scanner.ota_fetch.run_fetch',return_value=0) as ota, patch('trading_scanner.workflow.run_daily',return_value=0) as daily, redirect_stdout(io.StringIO()):
                self.assertEqual(execute_job(self.root,job),0)
            if task=='ota':
                self.assertTrue(ota.call_args.kwargs['use_stored_token'])
            else:
                self.assertTrue(daily.call_args.args[1].use_stored_token)
            report=json.loads((self.root/'artifacts/agent-review'/f"{job['id']}.json").read_text())
            self.assertIsNone(report['error_code'])

    def test_simultaneous_claims_are_serialized(self):
        from threading import Barrier, Thread
        self.service.configure(self.settings)
        barrier, outcomes = Barrier(2), []
        def claim():
            barrier.wait()
            try:
                outcomes.append(ScheduleService(self.root).claim(self.now))
            except DataError as exc:
                outcomes.append(exc.args[0])
        threads = [Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sum(isinstance(value,dict) for value in outcomes),1)
        self.assertIn('SCHEDULE_BUSY',outcomes)

    def test_offline_runner_denies_native_sqlite_reads_outside_synthetic_root(self):
        import sqlite3
        with self.assertRaisesRegex(PermissionError, 'OFFLINE_DATABASE_DENIED'):
            sqlite3.connect(__file__)

    def test_cancelled_provider_return_stops_long_running_worker(self):
        from argparse import Namespace
        from trading_scanner.schedule_cli import run_schedule
        with patch('trading_scanner.schedule_cli.ScheduleService') as service, patch('trading_scanner.schedule_cli.time.sleep') as sleep, redirect_stdout(io.StringIO()):
            service.return_value.tick.return_value = {'status':'cancelled'}
            service.return_value.view.return_value = {'next_due_local':None,'blocked_by_running_job':False,'settings':{'enabled':True}}
            self.assertEqual(run_schedule(self.root,Namespace(command='schedule-worker',once=False)),130)
            sleep.assert_not_called()

    def test_daily_preserves_cancellation_and_does_not_run_later_stages(self):
        from argparse import Namespace
        from trading_scanner.workflow import run_daily
        args=Namespace(page_size=100,max_pages=100,use_stored_token=True,filters=None)
        for public_code, ota_code in ((130,0),(0,130)):
            with patch('trading_scanner.scan_service.run_scan',return_value=public_code), patch('trading_scanner.ota_fetch.run_fetch',return_value=ota_code) as fetch, patch('trading_scanner.workflow.run_dashboard') as dashboard:
                self.assertEqual(run_daily(self.root,args),130)
                dashboard.assert_not_called()
                if public_code:
                    fetch.assert_not_called()
