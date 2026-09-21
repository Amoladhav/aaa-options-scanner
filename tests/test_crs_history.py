"""Synthetic-only history migration, session isolation and reproducible replay."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime
import io
import json
import sqlite3
import unittest
from unittest.mock import patch

from offline_boundary import temp
from trading_scanner.catalog import Catalog, MIGRATIONS, encoded
from trading_scanner.cli import main
from trading_scanner.core import DataError
from trading_scanner.crs_history import CRSHistory, method_key
from trading_scanner.demo import make_snapshot
from trading_scanner.report_service import ReportService


class CRSHistoryTests(unittest.TestCase):
    def setUp(self):
        self.root = temp / ('crs-' + self._testMethodName)
        self.catalog = Catalog(self.root)
        self.catalog.initialize()
        self.service = ReportService(self.catalog)
        self.history = CRSHistory(self.catalog)
        self.snapshot = make_snapshot()
        self.now = datetime.fromisoformat(self.snapshot['as_of'] + 'T22:00:00+00:00')

    def price(self, snapshot):
        return self.catalog.publish(encoded(snapshot), kind='prices',profile=snapshot['profile'],
                                    master=snapshot['universe'],observed_at=snapshot['membership_observed_at'])

    def generate(self, snapshot=None, **kwargs):
        with redirect_stdout(io.StringIO()):
            return self.service.generate(self.price(snapshot or self.snapshot),now=self.now,**kwargs)

    def earlier(self, count=1):
        snapshot = deepcopy(self.snapshot)
        snapshot['sessions'] = snapshot['sessions'][:-count]
        snapshot['as_of'] = snapshot['sessions'][-1]
        snapshot['membership_observed_at'] = snapshot['as_of']
        return snapshot

    def test_v1_upgrade_preserves_files_and_failure_rolls_back(self):
        catalog = Catalog(temp/'history-v1-upgrade')
        catalog.initialize(MIGRATIONS[:1])
        source = catalog.publish(b'{}',kind='prices',profile='synthetic')
        broken = catalog.root/'broken.sql'
        broken.write_text('CREATE TABLE crs_runs (id TEXT);\nINVALID SQL;\n',encoding='utf-8')
        with self.assertRaises(sqlite3.Error):
            catalog.initialize((MIGRATIONS[0],broken))
        with catalog.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='crs_runs'").fetchone())
        catalog.initialize(); catalog.initialize()
        self.assertEqual(catalog.read(source),b'{}')
        with self.assertRaisesRegex(DataError,'CATALOG_SCHEMA_INVALID'):
            catalog.initialize(MIGRATIONS[:1])

    def test_same_session_append_only_canonical_and_immutable_rows(self):
        first, second = self.generate(), self.generate()
        self.assertNotEqual(first,second)
        history = self.history.list('synthetic')
        self.assertEqual([r['artifact_id'] for r in history],[second,first])
        self.assertEqual([r['canonical'] for r in history],[1,0])
        self.assertEqual(len(self.history.show(first)['rows']),60)
        self.assertIsNone(self.service.load(second)['previous_session'])
        with self.catalog.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM canonical_sessions').fetchone()[0],1)
            for table in ('crs_runs','crs_results'):
                with self.assertRaisesRegex(sqlite3.IntegrityError,'HISTORY_IMMUTABLE'):
                    db.execute('DELETE FROM ' + table)
                with self.assertRaisesRegex(sqlite3.IntegrityError,'HISTORY_IMMUTABLE'):
                    db.execute('UPDATE ' + table + ' SET run_id=run_id')

    def test_prior_pinned_and_replay_ignores_new_canonical_revisions(self):
        prior = self.generate(self.earlier())
        original = self.generate()
        changed = self.earlier()
        changed['prices']['S00'][changed['as_of']] *= 1.5
        replacement = self.generate(changed)
        self.assertNotEqual(replacement,prior)
        self.assertEqual(self.history.prior(self.snapshot),replacement)
        with redirect_stdout(io.StringIO()):
            replay = self.service.replay(original)
        before, after = self.service.load(original), self.service.load(replay)
        self.assertEqual(after['combined'],before['combined'])
        self.assertEqual(after['generated_at'],before['generated_at'])
        self.assertEqual(after['filters'],before['filters'])
        self.assertEqual(after['history_provenance']['prior_artifact_id'],prior)
        self.assertEqual(after['history_provenance']['replay_of'],original)
        self.assertIn(prior,self.catalog.inputs(self.catalog.record(replay)['run_id']))
        self.assertIn(original,self.catalog.inputs(self.catalog.record(replay)['run_id']))
        current = [r for r in self.history.list('synthetic') if r['price_session']==self.snapshot['as_of']]
        self.assertEqual([r['artifact_id'] for r in current if r['canonical']],[original])

    def test_replay_without_prior_does_not_acquire_later_imported_history(self):
        original = self.generate()
        self.generate(self.earlier())
        with redirect_stdout(io.StringIO()):
            replay = self.service.replay(original)
        self.assertIsNone(self.service.load(replay)['previous_session'])
        with patch('trading_scanner.scan_service.code_revision',return_value='new-version'):
            with self.assertRaisesRegex(DataError,'HISTORY_REPLAY_VERSION_MISMATCH'):
                self.service.replay(original)

    def test_gaps_master_changes_and_excluded_rows_are_explicit(self):
        prior = self.generate(self.earlier(2))
        changed = deepcopy(self.snapshot)
        changed['universe'] = [r for r in changed['universe'] if r['symbol']!='S00']
        del changed['prices']['S01']
        current = self.generate(changed)
        result = self.service.load(current)
        self.assertTrue(result['history_provenance']['master_changed'])
        self.assertTrue(any(r['history_status']=='history_gap' for r in result['combined']))
        excluded = next(r for r in self.history.show(current)['rows'] if r['symbol']=='S01')
        self.assertEqual(excluded['status'],'excluded')
        self.assertIsNone(excluded['rank'])
        self.assertIsNone(excluded['r21'])
        self.assertEqual(excluded['exclusion_reason'],'STALE_PRICE')
        comparison = self.history.compare(prior,current)
        self.assertTrue(comparison['master_changed'])
        self.assertEqual(next(r for r in comparison['changes'] if r['symbol']=='S00')['membership'],'departed')

    def test_profile_method_and_cutoff_isolation(self):
        future = self.generate()
        self.assertIsNone(self.history.prior(self.earlier()))
        public = self.earlier(); public['profile']='public'
        other = self.generate(public)
        self.assertIsNone(self.history.prior(self.snapshot))
        with self.assertRaisesRegex(DataError,'HISTORY_COMPARISON_INCOMPATIBLE'):
            self.history.compare(future,other)
        with self.assertRaisesRegex(DataError,'HISTORY_INVALID'):
            self.history.previous(other,self.snapshot)
        earlier = self.generate(self.earlier())
        with patch('trading_scanner.crs_history.CALCULATION_VERSION','different-method'):
            self.assertIsNone(self.history.prior(self.snapshot))
        changed_calendar = deepcopy(self.snapshot)
        changed_calendar['sessions'].remove(self.earlier()['as_of'])
        self.assertIsNone(self.history.prior(changed_calendar))
        self.assertEqual(self.history.prior(self.snapshot),earlier)

    def test_transaction_failure_does_not_publish_partial_history(self):
        source = self.price(self.snapshot)
        with self.catalog.connection() as db:
            db.execute("CREATE TRIGGER fail_history BEFORE INSERT ON crs_results BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with redirect_stdout(io.StringIO()), self.assertRaises(sqlite3.IntegrityError):
            self.service.generate(source,now=self.now)
        self.assertEqual(len(self.catalog.runs()),1)
        self.assertEqual(self.history.list('synthetic'),[])
        with self.catalog.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM canonical_sessions').fetchone()[0],0)
        self.assertEqual(self.catalog.reconcile()['orphans'],1)

    def test_future_calendar_entries_do_not_change_prior_session_labels(self):
        prior = self.generate(self.earlier(2))
        snapshot = deepcopy(self.snapshot)
        snapshot['as_of'] = snapshot['sessions'][-2]
        current = self.generate(snapshot)
        result = self.service.load(current)
        self.assertEqual(result['history_provenance']['prior_artifact_id'],prior)
        self.assertEqual({row['history_status'] for row in result['combined']},{'previous_session'})

    def test_missing_or_changed_prior_fails_without_silent_fallback(self):
        prior = self.generate(self.earlier())
        path = self.root/self.catalog.record(prior)['relative_path']
        path.write_bytes(b'{}')
        with self.assertRaisesRegex(DataError,'CATALOG_ARTIFACT_CHANGED'):
            self.generate()
        path.unlink()
        with self.assertRaisesRegex(DataError,'CATALOG_ARTIFACT_UNAVAILABLE'):
            self.history.show(prior)

    def test_legacy_reports_remain_readable_without_invented_history(self):
        old = self.catalog.publish(encoded({'legacy':True}),kind='report',profile='synthetic')
        self.assertEqual(self.service.load(old),{'legacy':True})
        with self.assertRaisesRegex(DataError,'HISTORY_NOT_RECORDED'):
            self.history.show(old)
        self.assertEqual(self.history.list('synthetic'),[])

    def test_projection_validates_exact_report_and_bad_rows(self):
        original = self.generate()
        result = self.service.load(original)
        result['combined'][0]['score'] = True
        with self.assertRaisesRegex(DataError,'HISTORY_INVALID'):
            self.catalog.publish(encoded(result),kind='report',profile='synthetic',history=result)
        result = self.service.load(original)
        with self.assertRaisesRegex(DataError,'HISTORY_INVALID'):
            self.catalog.publish(b'{}',kind='report',profile='synthetic',history=result)

    def test_cli_inspection_and_replay_with_sanitized_diagnostics(self):
        first, second = self.generate(self.earlier()), self.generate()
        commands = [['history-list','--profile','synthetic'], ['history-show','--report',second],
                    ['history-compare','--left',first,'--right',second], ['report-replay','--report',second],
                    ['report-build','--prices',self.price(self.snapshot)]]
        for command in commands:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main(command,self.root),0)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['history-show','--report','synthetic-private-marker'],self.root),1)
        self.assertNotIn('synthetic-private-marker',output.getvalue())
        for path in self.root.glob('artifacts/agent-review/*.json'):
            data = path.read_text(encoding='utf-8')
            self.assertNotIn('S00',data)
            self.assertNotIn('synthetic-private-marker',data)

    def test_demo_history_cli_uses_separate_workspace(self):
        self.generate()
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['history-list','--profile','synthetic','--demo'],self.root),0)
        self.assertIn('[]',output.getvalue())
        self.assertEqual(len(self.history.list('synthetic')),1)
        self.assertTrue((self.root/'artifacts/web-demo-workspace/artifacts/catalog/catalog.sqlite3').is_file())

    def test_cancelled_history_command_never_reports_success(self):
        with patch.object(CRSHistory,'list',side_effect=KeyboardInterrupt()), redirect_stdout(io.StringIO()):
            self.assertEqual(main(['history-list','--profile','synthetic'],self.root),130)
        report=json.loads(next(self.root.glob('artifacts/agent-review/*.json')).read_text(encoding='utf-8'))
        self.assertEqual(report['error_code'],'RUN_CANCELLED')
        self.assertEqual(report['checks'][0]['status'],'failed')
