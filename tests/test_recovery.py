"""Synthetic catalog recovery drills; guarded against real files/network/secrets."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime
import io
import json
import sqlite3
import unittest
from unittest.mock import patch

from offline_boundary import temp
from trading_scanner.catalog import Catalog, MIGRATIONS, encoded, digest
from trading_scanner.cli import main
from trading_scanner.core import DataError, calculate
from trading_scanner.dashboard import save_history
from trading_scanner.demo import make_snapshot
from trading_scanner.legacy_history import LegacyHistory
from trading_scanner.recovery import RecoveryService, MANIFEST, stream_file
from trading_scanner.report_service import ReportService


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.root = temp/self._testMethodName
        self.catalog = Catalog(self.root); self.catalog.initialize()
        self.service = RecoveryService(self.root)
        self.backup = temp/(self._testMethodName+'-backup')
        self.target = temp/(self._testMethodName+'-restored')
        self.aid = self.catalog.publish(b'{"synthetic":true}',kind='prices',profile='synthetic')
        self.enterContext(redirect_stdout(io.StringIO()))

    def manifest(self):
        return json.loads((self.backup/MANIFEST).read_text(encoding='utf-8'))

    def test_roundtrip_old_schema_migrates_only_restored_copy(self):
        old = Catalog(temp/(self._testMethodName+'-old')); old.initialize(MIGRATIONS[:1])
        aid = old.publish(b'{}',kind='prices',profile='synthetic')
        service = RecoveryService(old.root)
        service.backup(self.backup)
        before = (self.backup/'artifacts/catalog/catalog.sqlite3').read_bytes()
        self.assertEqual(service.verify(self.backup)['database_schema'],1)
        service.restore(self.backup,self.target)
        restored = Catalog(self.target)
        self.assertEqual(restored.read(aid),b'{}')
        with restored.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],3)
        self.assertEqual((self.backup/'artifacts/catalog/catalog.sqlite3').read_bytes(),before)
        with old.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],1)

    def test_restored_reports_replay_legacy_pins_and_rollback_state(self):
        snapshot = make_snapshot(); old = deepcopy(snapshot)
        old['sessions'] = old['sessions'][:-1]
        old['as_of'] = old['membership_observed_at'] = old['sessions'][-1]
        save_history(self.root/'artifacts/history/synthetic',calculate(old))
        legacy = LegacyHistory(self.catalog)
        batch = legacy.apply('synthetic',legacy.preview('synthetic')['preview_id'])
        service = ReportService(self.catalog)
        aid = service.generate_from_payloads(snapshot,None,now=datetime.fromisoformat(snapshot['as_of']+'T22:00:00+00:00'))
        legacy.rollback(batch['batch_id'])
        self.service.backup(self.backup)
        self.service.restore(self.backup,self.target)
        restored = ReportService(Catalog(self.target))
        original = service.load(aid)
        self.assertEqual(restored.load(aid),original)
        self.assertEqual(restored.load(restored.replay(aid))['combined'],original['combined'])
        self.assertEqual(LegacyHistory(Catalog(self.target)).batches('synthetic')[0]['state'],'rolled_back')
        self.assertFalse((self.target/'artifacts/history').exists())

    def test_only_registered_files_and_database_are_packaged(self):
        for relative in ('.env','.secrets/example','artifacts/logs/private.log','artifacts/scheduler/schedule.sqlite3',
                         'artifacts/ota/raw.json','artifacts/catalog/files/orphan.json','config/personal.json'):
            path=self.root/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('synthetic excluded marker')
        self.service.backup(self.backup)
        files={p.relative_to(self.backup).as_posix() for p in self.backup.rglob('*') if p.is_file()}
        self.assertEqual(files,{MANIFEST,'artifacts/catalog/catalog.sqlite3',f'artifacts/catalog/files/{self.aid}.json'})
        self.assertEqual(self.manifest()['scope'],'catalog')

    def test_missing_or_changed_source_never_publishes_manifest(self):
        path=self.root/self.catalog.record(self.aid)['relative_path'];path.write_bytes(b'changed')
        with self.assertRaisesRegex(DataError,'RECOVERY_CHANGED'):
            self.service.backup(self.backup)
        self.assertFalse((self.backup/MANIFEST).exists())
        with self.assertRaisesRegex(DataError,'RECOVERY_INVALID'):
            self.service.verify(self.backup)
        path.unlink()
        with self.assertRaisesRegex(DataError,'RECOVERY_INVALID'):
            self.service.backup(temp/(self._testMethodName+'-missing'))

    def test_corrupt_database_manifest_and_artifact_rejected_before_restore(self):
        self.service.backup(self.backup)
        manifest_path=self.backup/MANIFEST;original=manifest_path.read_bytes()
        manifest_path.write_bytes(b'{}')
        with self.assertRaises(DataError): self.service.restore(self.backup,self.target)
        self.assertFalse(self.target.exists())
        manifest_path.write_bytes(original)
        artifact=self.backup/self.manifest()['files'][0]['path'];data=artifact.read_bytes();artifact.write_bytes(b'changed')
        with self.assertRaisesRegex(DataError,'RECOVERY_CHANGED'): self.service.restore(self.backup,self.target)
        artifact.write_bytes(data)
        database=self.backup/'artifacts/catalog/catalog.sqlite3';database.write_bytes(b'not sqlite')
        with self.assertRaisesRegex(DataError,'RECOVERY_CHANGED'): self.service.restore(self.backup,self.target)
        self.assertFalse(self.target.exists())

    def test_foreign_schema_rejected_even_with_updated_manifest_hash(self):
        self.service.backup(self.backup)
        path=self.backup/'artifacts/catalog/catalog.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE unexpected (value TEXT)')
        manifest=self.manifest();manifest['database']=stream_file(path,512_000_000)
        (self.backup/MANIFEST).write_bytes(encoded(manifest))
        with self.assertRaisesRegex(DataError,'RECOVERY_INVALID'):
            self.service.restore(self.backup,self.target)
        self.assertFalse(self.target.exists())

    def test_manifest_cannot_redirect_artifact_paths(self):
        self.service.backup(self.backup)
        manifest=self.manifest();manifest['files'][0]['path']='../../.env'
        (self.backup/MANIFEST).write_bytes(encoded(manifest))
        with self.assertRaisesRegex(DataError,'RECOVERY_CHANGED'):
            self.service.verify(self.backup)
        with patch('pathlib.Path.is_symlink',return_value=True):
            with self.assertRaisesRegex(DataError,'RECOVERY_INVALID'):
                self.service.verify(self.backup)

    def test_existing_destinations_never_overwritten(self):
        before=self.catalog.path.read_bytes()
        with self.assertRaises(DataError): self.service.backup(self.root)
        self.service.backup(self.backup)
        with self.assertRaisesRegex(DataError,'RECOVERY_DESTINATION_EXISTS'): self.service.backup(self.backup)
        with self.assertRaisesRegex(DataError,'RECOVERY_DESTINATION_EXISTS'): self.service.restore(self.backup,self.root)
        self.assertEqual(self.catalog.path.read_bytes(),before)

    def test_concurrent_publication_does_not_expand_snapshot_file_set(self):
        from trading_scanner import recovery
        original = recovery.file_set
        def concurrent(source,files,destination=None,progress=None):
            self.catalog.publish(b'{"later":true}',kind='prices',profile='synthetic')
            return original(source,files,destination,progress)
        with patch.object(recovery,'file_set',side_effect=concurrent):
            self.service.backup(self.backup)
        self.assertEqual(len(self.service.verify(self.backup)['files']),1)
        self.assertEqual(len(self.catalog.list_artifacts()),2)

    def test_interrupted_restore_has_no_published_catalog(self):
        self.service.backup(self.backup)
        with patch.object(Catalog,'initialize',side_effect=OSError('synthetic storage failure')):
            with self.assertRaises(OSError): self.service.restore(self.backup,self.target)
        self.assertFalse((self.target/'artifacts/catalog').exists())
        self.assertFalse((self.target/'restore-complete.json').exists())
        self.assertTrue((self.target/'.restore-pending').exists())

    def test_cli_progress_sanitized_reports_and_cancellation(self):
        commands=[['catalog-backup','--destination',str(self.backup)],
                  ['catalog-backup-verify','--backup',str(self.backup)],
                  ['catalog-restore','--backup',str(self.backup),'--destination',str(self.target)]]
        for command in commands:
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(command,self.root),0)
            self.assertIn('completed',output.getvalue().lower())
            self.assertNotIn('\x1b',output.getvalue())
        with patch.object(RecoveryService,'backup',side_effect=KeyboardInterrupt()):
            self.assertEqual(main(commands[0],self.root),130)
        reports=[json.loads(p.read_text()) for p in self.root.glob('artifacts/agent-review/*.json')]
        self.assertEqual(sum(r['error_code']=='RUN_CANCELLED' for r in reports),1)
        for report in reports:
            self.assertNotIn(self.aid,json.dumps(report))
            self.assertNotIn(str(self.backup),json.dumps(report))

    def test_limits_reject_without_completion(self):
        with patch('trading_scanner.recovery.MAX_FILES',0):
            with self.assertRaisesRegex(DataError,'RECOVERY_LIMIT'): self.service.backup(self.backup)
        self.assertFalse((self.backup/MANIFEST).exists())

    def test_sqlite_backup_includes_committed_wal_data(self):
        with self.catalog.connection() as keeper:
            self.assertEqual(keeper.execute('PRAGMA journal_mode=WAL').fetchone()[0], 'wal')
            keeper.execute('BEGIN')
            keeper.execute('SELECT count(*) FROM artifacts').fetchone()
            aid = self.catalog.publish(b'{"wal":true}',kind='prices',profile='synthetic')
            self.assertTrue(self.catalog.path.with_name('catalog.sqlite3-wal').exists())
            self.service.backup(self.backup)
        self.service.restore(self.backup,self.target)
        self.assertEqual(Catalog(self.target).read(aid),b'{"wal":true}')

    def test_backup_deadline_and_storage_failure_do_not_report_success(self):
        with patch('trading_scanner.recovery.monotonic',side_effect=(0,31)):
            with self.assertRaisesRegex(DataError,'RECOVERY_BUSY'):
                self.service.backup(self.backup)
        self.assertFalse((self.backup/MANIFEST).exists())
        destination = temp/(self._testMethodName+'-write-failed')
        with patch('trading_scanner.recovery.file_set',side_effect=OSError('synthetic-private-marker')):
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['catalog-backup','--destination',str(destination)],self.root),1)
        self.assertNotIn('synthetic-private-marker',output.getvalue())
        self.assertFalse((destination/MANIFEST).exists())

    def test_missing_backup_artifact_and_migration_checksum_rejected(self):
        self.service.backup(self.backup)
        path = self.backup/'artifacts/catalog/catalog.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute("UPDATE schema_migrations SET checksum='invalid' WHERE version=1")
        manifest=self.manifest();manifest['database']=stream_file(path,512_000_000)
        (self.backup/MANIFEST).write_bytes(encoded(manifest))
        with self.assertRaisesRegex(DataError,'RECOVERY_INVALID'):
            self.service.verify(self.backup)
        second = temp/(self._testMethodName+'-second')
        self.service.backup(second)
        (second/f'artifacts/catalog/files/{self.aid}.json').unlink()
        with self.assertRaisesRegex(DataError,'RECOVERY_INVALID'):
            self.service.verify(second)
