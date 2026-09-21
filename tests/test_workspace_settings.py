"""Synthetic screeners/preferences, conflicts and recovery parity."""
from contextlib import redirect_stdout
from dataclasses import replace
from datetime import datetime
import io,json,sqlite3,unittest
from offline_boundary import temp
from trading_scanner.catalog import Catalog,encoded
from trading_scanner.cli import main
from trading_scanner.core import DataError
from trading_scanner.demo import make_snapshot
from trading_scanner.report_service import ReportService,csv_export
from trading_scanner.report_selection import Selection,ColumnFilter,select_rows,watchlist_export
from trading_scanner.workspace_settings import WorkspaceSettings,selection_payload,preferences
from trading_scanner.recovery import RecoveryService

class WorkspaceSettingsTests(unittest.TestCase):
    def setUp(self):
        self.root=temp/self._testMethodName;self.catalog=Catalog(self.root);self.catalog.initialize()
        self.service=WorkspaceSettings(self.catalog)
        self.enterContext(redirect_stdout(io.StringIO()))
        snapshot=make_snapshot()
        self.report=ReportService(self.catalog).generate_from_payloads(snapshot,None,now=datetime.fromisoformat(snapshot['as_of']+'T22:00:00+00:00'))
        self.result=ReportService(self.catalog).load(self.report)

    def save(self,selection=Selection(),name='Example',expected=None):
        return self.service.save('screener',name,selection_payload(selection),source=self.report,expected=expected)

    def test_selection_revisions_pin_applied_membership_and_exports(self):
        selected=Selection(filters=(ColumnFilter('score','gt','0'),),columns=('symbol','score'),tail='top',percent=20,page=3)
        first=self.save(selected);second=self.save(Selection(group='etf'),expected=first)
        restored=self.service.apply(first,self.result)
        self.assertEqual(restored.page,1)
        self.assertEqual(select_rows(self.result,restored),select_rows(self.result,selected))
        self.assertEqual(csv_export(self.result,restored),csv_export(self.result,selected))
        self.assertEqual(watchlist_export(self.result,restored),watchlist_export(self.result,selected))
        self.assertEqual(self.service.list()[0]['revision_id'],second)
        self.assertEqual(self.service.get(second)['predecessor'],first)
        self.assertEqual(len(self.service.history('screener','Example')),2)

    def test_stale_update_and_immutable_rows(self):
        first=self.save();second=self.save(expected=first)
        with self.assertRaisesRegex(DataError,'SETTINGS_CONFLICT'):self.save(expected=first)
        with self.assertRaisesRegex(DataError,'SETTINGS_CONFLICT'):self.save()
        self.assertEqual(self.service.current('screener','Example')['id'],second)
        with self.catalog.connection() as db:
            for sql in ('DELETE FROM workspace_revisions','UPDATE workspace_revisions SET name=name'):
                with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)

    def test_unknown_columns_fail_without_partial_preset(self):
        with self.assertRaisesRegex(DataError,'REPORT_COLUMN_UNKNOWN'):
            self.save(Selection(columns=('not_a_column',)))
        self.assertEqual(self.service.list(),[])
        custom={**self.result,'ota_raw_fields':['synthetic_field']}
        aid=self.catalog.publish(encoded(custom),kind='report',profile='synthetic')
        revision=self.service.save('screener','Custom',selection_payload(Selection(columns=('ota_raw.synthetic_field',))),source=aid)
        with self.assertRaisesRegex(DataError,'REPORT_COLUMN_UNKNOWN'):
            self.service.apply(revision,self.result)

    def test_preferences_explicit_validation_and_revision(self):
        revision,value=self.service.preference_state();self.assertIsNone(revision)
        self.assertEqual(value,{'page_size':25,'display_timezone':'local'})
        first=self.service.save('preferences','workspace',{'page_size':100,'display_timezone':'utc'})
        self.assertEqual(self.service.preference_state()[0],first)
        with self.assertRaisesRegex(DataError,'SETTINGS_CONFLICT'):
            self.service.save('preferences','workspace',value)
        for bad in ({**value,'page_size':True},{**value,'display_timezone':'invented'},{**value,'token':'synthetic'}):
            with self.assertRaisesRegex(DataError,'SETTINGS_INVALID'):preferences(bad)

    def test_invalid_names_payload_versions_and_unknown_fields(self):
        for name in ('','../private','<script>',' padded'):
            with self.assertRaisesRegex(DataError,'SETTINGS_INVALID'):self.save(name=name)
        payload=selection_payload(Selection())
        for bad in ({**payload,'version':2},{**payload,'extra':True},{'version':1,'selection':{}}):
            with self.assertRaises(DataError):self.service.save('screener','Example',bad,source=self.report)
        self.assertEqual(self.service.list(),[])

    def test_catalog_recovery_includes_preferences_and_all_revisions(self):
        first=self.save();second=self.save(Selection(tail='bottom'),expected=first)
        pref=self.service.save('preferences','workspace',{'page_size':50,'display_timezone':'utc'})
        recovery=RecoveryService(self.root);backup=temp/(self._testMethodName+'-backup');target=temp/(self._testMethodName+'-restore')
        recovery.backup(backup);recovery.restore(backup,target)
        restored=WorkspaceSettings(Catalog(target))
        self.assertEqual(restored.get(first),self.service.get(first))
        self.assertEqual(restored.current('screener','Example')['id'],second)
        self.assertEqual(restored.preference_state()[0],pref)

    def test_cli_same_service_and_no_values_in_review(self):
        path=self.root/'selection.json';path.write_bytes(encoded(selection_payload(Selection(search='synthetic-private-marker'))))
        self.assertEqual(main(['screener-save','--name','Private name','--report',self.report,'--selection-file',str(path)],self.root),0)
        revision=self.service.list()[0]['revision_id']
        for args in (['screener-list'],['screener-show','--revision',revision],['preferences-show'],['preferences-set','--page-size','50','--display-timezone','utc']):
            self.assertEqual(main(args,self.root),0)
        destination=self.root/'selected.csv'
        self.assertEqual(main(['screener-export','--revision',revision,'--report',self.report,'--destination',str(destination)],self.root),0)
        self.assertEqual(destination.read_bytes(),csv_export(self.result,self.service.apply(revision,self.result)))
        for path in self.root.glob('artifacts/agent-review/*.json'):
            text=path.read_text();self.assertNotIn('synthetic-private-marker',text);self.assertNotIn('Private name',text)
