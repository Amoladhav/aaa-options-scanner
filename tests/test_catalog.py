"""Temporary-only catalog migration, durable publication and boundary tests."""
import sqlite3
from pathlib import Path
import unittest
from unittest.mock import patch
from offline_boundary import temp
from trading_scanner.catalog import Catalog, MIGRATIONS, encoded, confined
from trading_scanner.core import DataError


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.root = temp / self._testMethodName
        self.catalog = Catalog(self.root)
        self.catalog.initialize()

    def test_fresh_reopen_and_idempotent_index_legacy_ids(self):
        aid = self.catalog.publish(b'{"synthetic":true}', kind='prices', profile='synthetic', run_id='a'*32)
        self.assertEqual(self.catalog.publish(b'{"synthetic":true}',kind='prices',profile='synthetic'), aid)
        self.catalog.initialize()
        self.assertEqual(self.catalog.read(aid), b'{"synthetic":true}')
        self.assertEqual(self.catalog.list_artifacts()[0]['run_id'], 'a'*32)
        self.assertEqual(self.catalog.reconcile(), {'available':1,'missing':0,'changed':0,'orphans':0,'pending':0})
        self.assertFalse((self.root/'artifacts/scheduler').exists())

    def test_upgrade_and_failed_migration_roll_back(self):
        migration = self.root/'002.sql'
        migration.write_text('CREATE TABLE example (id INTEGER);\nINVALID SQL;\n')
        with self.assertRaises(sqlite3.Error):
            self.catalog.initialize((*MIGRATIONS,migration))
        with self.catalog.connection() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='example'").fetchone())
        migration.write_text('CREATE TABLE example (id INTEGER);\n')
        self.catalog.initialize((*MIGRATIONS,migration))
        with self.assertRaisesRegex(DataError, 'CATALOG_SCHEMA_INVALID'):
            self.catalog.initialize()
        migration.write_text('CREATE TABLE example (id TEXT);\n')
        with self.assertRaisesRegex(DataError, 'CATALOG_SCHEMA_INVALID'):
            self.catalog.initialize((*MIGRATIONS,migration))

    def test_foreign_keys_and_input_lineage(self):
        aid = self.catalog.publish(b'{}',kind='prices',profile='synthetic')
        report = self.catalog.publish(b'{}',kind='report',profile='synthetic',input_ids=[aid])
        self.assertEqual(self.catalog.inputs(self.catalog.record(report)['run_id']), [aid])
        with self.catalog.connection() as db, self.assertRaises(sqlite3.IntegrityError):
            db.execute('INSERT INTO run_inputs VALUES (?,?,?)', ('missing', aid, 0))
        with self.assertRaises(DataError):
            self.catalog.publish(b'{}',kind='report',profile='synthetic',input_ids=['f'*32])

    def test_publication_failure_orphan_and_pending_are_visible(self):
        # Collision rejects database registration after file publication.
        self.catalog.publish(b'{}',kind='prices',profile='synthetic',run_id='b'*32)
        with self.assertRaises(sqlite3.IntegrityError):
            self.catalog.publish(b'{"different":true}',kind='prices',profile='synthetic',run_id='b'*32)
        counts = self.catalog.reconcile()
        self.assertEqual(counts['orphans'],1)
        self.assertEqual(len(self.catalog.runs()),1)
        with patch('trading_scanner.catalog.os.fsync',side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                self.catalog.publish(b'{}',kind='ota',profile='synthetic')
        self.assertEqual(self.catalog.reconcile()['pending'],1)
        self.assertEqual(len(self.catalog.runs()),1)

    def test_missing_changed_and_path_escape(self):
        aid = self.catalog.publish(b'{}',kind='prices',profile='synthetic')
        path = self.root / self.catalog.record(aid)['relative_path']
        path.write_bytes(b'[]')
        with self.assertRaisesRegex(DataError,'CATALOG_ARTIFACT_CHANGED'):
            self.catalog.read(aid)
        self.assertEqual(self.catalog.reconcile()['changed'],1)
        path.unlink()
        self.assertEqual(self.catalog.reconcile()['missing'],1)
        for bad in ('../outside', '/etc/passwd', 'C:/outside', 'artifacts/../config', 'artifacts\\outside'):
            with self.assertRaises(DataError):
                confined(self.root,bad)
        with self.assertRaises(DataError):
            self.catalog.read('../../secret')

    def test_symlink_component_is_rejected(self):
        # Exercise the policy even when this machine cannot create real links.
        link = self.root / 'link'
        with patch.object(Path, 'is_symlink', autospec=True,
                          side_effect=lambda path: path == link):
            with self.assertRaisesRegex(DataError, 'CATALOG_PATH_INVALID'):
                confined(self.root, 'link/file')

    def test_real_symlink_component_is_rejected(self):
        target = self.root / 'target'
        target.mkdir()
        try:
            (self.root / 'link').symlink_to(target, target_is_directory=True)
        except OSError as exc:
            # Ordinary Windows sessions may lack link-creation privileges.
            # Skip only that capability check; unrelated filesystem errors fail.
            if getattr(exc, 'winerror', None) == 1314:
                self.skipTest('Windows symlink creation privilege unavailable (1314)')
            raise
        with self.assertRaisesRegex(DataError, 'CATALOG_PATH_INVALID'):
            confined(self.root, 'link/file')

    def test_metadata_cannot_redirect_to_other_workspace_files(self):
        aid = self.catalog.publish(b'{}',kind='prices',profile='synthetic')
        with self.catalog.connection() as db:
            db.execute('UPDATE artifacts SET relative_path=? WHERE id=?',('config/example.json',aid))
        with self.assertRaisesRegex(DataError,'CATALOG_ARTIFACT_UNAVAILABLE'):
            self.catalog.read(aid)

    def test_master_versions_and_settings_persist_without_provider_payloads(self):
        from trading_scanner.dashboard import FILTER_DEFAULTS
        aid = self.catalog.publish(encoded({'synthetic':True}),kind='prices',profile='synthetic',
                                   master=[{'symbol':'AAA','group':'stock'}],settings=FILTER_DEFAULTS)
        with self.catalog.connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM master_members').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT count(*) FROM settings_revisions').fetchone()[0],1)
        self.assertIsNotNone(self.catalog.runs()[0]['master_id'])

    def test_user_run_index_validates_source_and_keeps_bytes(self):
        from trading_scanner.catalog_service import index_source
        from trading_scanner.demo import make_snapshot
        snapshot = make_snapshot();snapshot['profile']='public'
        path=self.root/'artifacts/runs/public/fixture/snapshot.json'
        path.parent.mkdir(parents=True)
        data=encoded(snapshot);path.write_bytes(data)
        aid=index_source(self.catalog,path,'prices')
        self.assertEqual(self.catalog.read(aid),data)
        self.assertEqual(index_source(self.catalog,path,'prices'),aid)
        self.assertEqual(path.read_bytes(),data)
        with self.assertRaises(DataError):
            index_source(self.catalog,self.root/'config/credentials.json','prices')

    def test_catalog_cli_initializes_without_scheduler_and_redacts_failure(self):
        import io,json
        from contextlib import redirect_stdout
        from trading_scanner.cli import main
        output=io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['catalog-init'],self.root),0)
            self.assertEqual(main(['catalog-index','--kind','ota','--input','synthetic-private-path'],self.root),1)
        self.assertNotIn('synthetic-private-path',output.getvalue())
        self.assertFalse((self.root/'artifacts/scheduler').exists())
        reports=[json.loads(p.read_text()) for p in self.root.glob('artifacts/agent-review/*.json')]
        self.assertEqual(len(reports),2)
