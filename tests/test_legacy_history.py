"""Legacy imports operate only on synthetic temporary workspaces."""
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
from trading_scanner.core import DataError, calculate
from trading_scanner.crs_history import CRSHistory
from trading_scanner.dashboard import save_history, synthetic_ota
from trading_scanner.demo import make_snapshot
from trading_scanner.legacy_history import LegacyHistory
from trading_scanner.report_service import ReportService


class LegacyHistoryTests(unittest.TestCase):
    def setUp(self):
        self.root = temp / self._testMethodName
        self.catalog = Catalog(self.root)
        self.legacy = LegacyHistory(self.catalog)
        self.snapshot = make_snapshot()
        self.old = deepcopy(self.snapshot)
        self.old['sessions'] = self.old['sessions'][:-1]
        self.old['as_of'] = self.old['membership_observed_at'] = self.old['sessions'][-1]
        self.directory = self.root / 'artifacts/history/synthetic'
        save_history(self.directory, calculate(self.old))
        self.path = self.directory / (self.old['as_of'] + '.json')
        self.original = self.path.read_bytes()
        self.now = datetime.fromisoformat(self.snapshot['as_of'] + 'T22:00:00+00:00')
        self.enterContext(redirect_stdout(io.StringIO()))

    def apply(self):
        return self.legacy.apply('synthetic', self.legacy.preview('synthetic')['preview_id'])

    def generate(self, snapshot=None):
        return ReportService(self.catalog).generate_from_payloads(snapshot or self.snapshot, None, now=self.now)

    def test_preview_no_catalog_creation_and_upgrade_only_on_apply(self):
        plan = self.legacy.preview('synthetic')
        self.assertEqual(plan['counts']['importable'], 1)
        self.assertFalse(self.catalog.path.exists())
        self.catalog.initialize(MIGRATIONS[:2])
        before = self.catalog.path.read_bytes()
        self.assertEqual(self.legacy.preview('synthetic'), plan)
        self.assertEqual(self.catalog.path.read_bytes(), before)
        self.apply()
        with self.catalog.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], len(MIGRATIONS))
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_duplicate_rollback_reimport_preserves_pinned_replay(self):
        batch = self.apply()
        history = CRSHistory(self.catalog)
        prior = history.prior(self.snapshot)
        self.assertEqual(self.apply()['imported'], 0)
        report = self.generate()
        service = ReportService(self.catalog)
        original = service.load(report)
        self.assertEqual(original['history_provenance']['legacy_prior_artifact_id'], prior)
        self.assertIsNone(original['history_provenance']['master_changed'])
        self.assertEqual(self.legacy.rollback(batch['batch_id'])['deactivated'], 1)
        self.assertEqual(self.legacy.rollback(batch['batch_id'])['deactivated'], 0)
        self.assertIsNone(history.prior(self.snapshot))
        replay = service.load(service.replay(report))
        self.assertEqual(replay['combined'], original['combined'])
        self.assertEqual(replay['history_provenance']['legacy_prior_artifact_id'], prior)
        self.assertEqual(self.apply()['imported'], 1)
        self.assertEqual(history.prior(self.snapshot), prior)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_stale_preview_source_and_catalog_changes(self):
        plan = self.legacy.preview('synthetic')
        self.path.write_bytes(self.original + b' ')
        with self.assertRaisesRegex(DataError, 'HISTORY_PREVIEW_STALE'):
            self.legacy.apply('synthetic', plan['preview_id'])
        plan = self.legacy.preview('synthetic')
        self.catalog.initialize()
        self.generate(self.old)
        with self.assertRaisesRegex(DataError, 'HISTORY_PREVIEW_STALE'):
            self.legacy.apply('synthetic', plan['preview_id'])

    def test_invalid_unsupported_conflict_and_session_selection(self):
        other = self.directory / '2000-01-03.json'
        other.write_bytes(b'{}')
        plan = self.legacy.preview('synthetic')
        self.assertEqual(plan['counts']['unsupported'], 1)
        with self.assertRaisesRegex(DataError, 'HISTORY_IMPORT_BLOCKED'):
            self.legacy.apply('synthetic', plan['preview_id'])
        session = self.old['as_of']
        plan = self.legacy.preview('synthetic', session)
        self.legacy.apply('synthetic', plan['preview_id'], session)
        self.path.write_bytes(self.original + b' ')
        self.assertEqual(self.legacy.preview('synthetic', session)['counts']['conflict'], 1)
        for data in (b'not-json', b'\xff', self.original.replace(b'"rank": 1,', b'"rank": true,')):
            self.path.write_bytes(data)
            self.assertEqual(self.legacy.preview('synthetic', session)['counts']['invalid'], 1)

    def test_atomic_failure_leaves_no_active_batch(self):
        self.catalog.initialize()
        with self.catalog.connection() as db:
            db.execute("CREATE TRIGGER fail_import BEFORE INSERT ON legacy_import_items BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.apply()
        self.assertEqual(self.legacy.batches('synthetic'), [])
        self.assertIsNone(CRSHistory(self.catalog).prior(self.snapshot))
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_catalog_wins_same_session_and_future_profiles_are_excluded(self):
        self.apply()
        history = CRSHistory(self.catalog)
        self.assertIsNone(history.prior(self.old))
        public = deepcopy(self.snapshot); public['profile'] = 'public'
        self.assertIsNone(history.prior(public))
        missing = deepcopy(self.snapshot); missing['sessions'].remove(self.old['as_of'])
        self.assertIsNone(history.prior(missing))
        current = self.generate(self.old)
        self.assertEqual(history.prior(self.snapshot), current)
        self.assertTrue(self.legacy.preview('synthetic')['entries'][0]['catalog_precedence'])

    def test_limits_and_path_validation(self):
        with patch('trading_scanner.legacy_history.MAX_FILE', 10):
            with self.assertRaisesRegex(DataError, 'HISTORY_IMPORT_LIMIT'):
                self.legacy.preview('synthetic')
        for session in ('../private', '2026-99-01', '20260101'):
            with self.assertRaisesRegex(DataError, 'HISTORY_INVALID'):
                self.legacy.preview('synthetic', session)
        with patch('pathlib.Path.is_symlink', return_value=True):
            with self.assertRaisesRegex(DataError, 'CATALOG_PATH_INVALID'):
                self.legacy.preview('synthetic')

    def test_cli_commands_and_aggregate_review_privacy(self):
        self.assertEqual(main(['history-preview', '--profile', 'synthetic'], self.root), 0)
        plan = self.legacy.preview('synthetic')
        self.assertEqual(main(['history-import', '--profile', 'synthetic', '--preview-id', plan['preview_id']], self.root), 0)
        self.assertEqual(main(['history-imports', '--profile', 'synthetic'], self.root), 0)
        batch = self.legacy.batches('synthetic')[0]['id']
        self.assertEqual(main(['history-rollback', '--batch', batch], self.root), 0)
        for path in self.root.glob('artifacts/agent-review/*.json'):
            text = path.read_text(encoding='utf-8')
            self.assertNotIn('S00', text)
            self.assertNotIn(batch, text)
            self.assertNotIn(plan['preview_id'], text)
            self.assertIsNone(json.loads(text)['error_code'])

    def test_standalone_dashboard_uses_import_without_rewriting_daily_files(self):
        self.apply()
        snapshot = deepcopy(self.snapshot); snapshot['profile'] = 'public'
        public_old = deepcopy(self.old); public_old['profile'] = 'public'
        directory = self.root / 'artifacts/history/public'
        save_history(directory, calculate(public_old))
        plan = self.legacy.preview('public')
        self.legacy.apply('public', plan['preview_id'])
        price_path = self.root / 'prices.json'; price_path.write_bytes(encoded(snapshot))
        ota = synthetic_ota(snapshot); ota['source'] = 'ota'; ota['coverage'] = 'short_page_observed'
        ota_path = self.root / 'ota.json'; ota_path.write_bytes(encoded(ota))
        before = {p.name:p.read_bytes() for p in directory.glob('*.json')}
        for _ in range(2):
            self.assertEqual(main(['dashboard', '--snapshot', str(price_path), '--ota', str(ota_path)], self.root), 0)
        reports = CRSHistory(self.catalog).list('public')
        self.assertEqual(len(reports), 2)
        self.assertEqual(sum(r['canonical'] for r in reports), 1)
        result = ReportService(self.catalog).load(reports[0]['artifact_id'])
        self.assertEqual(result['previous_session'], self.old['as_of'])
        self.assertIn('legacy_prior_artifact_id', result['history_provenance'])
        self.assertEqual({p.name:p.read_bytes() for p in directory.glob('*.json')}, before)

    def test_multiple_tradier_inputs_remain_pinned_for_replay(self):
        self.catalog.initialize()
        snapshot = deepcopy(self.snapshot); snapshot['profile'] = 'public'
        probes = [{'schema_version':1, 'source':'tradier', 'profile':'production',
                   'symbol':symbol, 'retrieved_at':self.now.isoformat(),
                   'expiration':'2026-10-16', 'expiration_type':'standard',
                   'atm_strike':100, 'call':{'strike':100}, 'put':{'strike':100}}
                  for symbol in ('S00', 'S01')]
        service = ReportService(self.catalog)
        report = service.generate_from_payloads(snapshot, None, probes=probes, now=self.now)
        original = service.load(report)
        self.assertEqual(len(original['source_artifact_ids']['tradier_extra']), 1)
        self.assertEqual(sum(r['tradier_status']=='supplied_freshness_unverified' for r in original['combined']), 2)
        self.assertEqual(service.load(service.replay(report))['combined'], original['combined'])

    def test_concurrent_activation_rejects_stale_state(self):
        self.catalog.initialize()
        original_publish = self.catalog.publish
        injected = False
        def publish(*args, **kwargs):
            nonlocal injected
            artifact = original_publish(*args, **kwargs)
            if not injected:
                injected = True
                self.apply()
            return artifact
        with patch.object(self.catalog, 'publish', side_effect=publish):
            with self.assertRaisesRegex(DataError, 'HISTORY_PREVIEW_STALE'):
                self.apply()
        self.assertEqual(len(self.legacy.batches('synthetic')), 1)
        self.assertEqual(self.path.read_bytes(), self.original)
