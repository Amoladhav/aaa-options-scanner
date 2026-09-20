"""Shared CLI/web calculation and export contracts, without web extras."""
from datetime import datetime
import csv
import io
import unittest
from contextlib import redirect_stdout
from offline_boundary import temp
from trading_scanner.demo import make_snapshot
from trading_scanner.dashboard import combine,attach_tradier,synthetic_ota,write_dashboard
from trading_scanner.catalog import Catalog
from trading_scanner.report_service import compose_report,Selection,select_rows,csv_export,ReportService
from trading_scanner.core import DataError

class ReportServiceTests(unittest.TestCase):
    def setUp(self):
        self.snapshot=make_snapshot();self.ota=synthetic_ota(self.snapshot)
        self.now=datetime.fromisoformat(self.ota['retrieved_at'])
        self.result=compose_report(self.snapshot,self.ota,now=self.now)

    def test_existing_composition_and_csv_parity(self):
        expected=combine(self.snapshot,self.ota,now=self.now);attach_tradier(expected,[])
        self.assertEqual(self.result,expected)
        root=temp/self._testMethodName;root.mkdir()
        write_dashboard(expected,root)
        self.assertEqual(csv_export(self.result),(root/'master.csv').read_bytes())

    def test_all_dataset_tails_and_filtered_export_ignore_page(self):
        for tail in ('top','bottom','both'):
            selection=Selection(tail=tail,percent=10,page=2)
            rows=select_rows(self.result,selection)
            expected=[r for r in self.result['combined'] if (tail in ('top','both') and r['percentile']>=.9) or (tail in ('bottom','both') and r['percentile']<=.1)]
            self.assertEqual({r['symbol'] for r in rows},{r['symbol'] for r in expected})
            parsed=list(csv.DictReader(io.StringIO(csv_export(self.result,selection).decode('utf-8-sig'))))
            self.assertEqual([r['symbol'] for r in parsed],[r['symbol'] for r in rows])

    def test_missing_ota_unranked_and_formula_protection(self):
        del self.snapshot['prices']['S01']
        result=compose_report(self.snapshot,None,now=self.now)
        self.assertEqual(len(result['combined']),60)
        self.assertEqual(result['ota_metadata']['coverage'],'not_supplied')
        self.assertTrue(all(r['ota_status']=='not_supplied' for r in result['combined']))
        self.assertEqual(select_rows(result,Selection())[-1]['symbol'],'S01')
        result['combined'][0]['company']='=SYNTHETIC_FORMULA()'
        self.assertIn("'=SYNTHETIC_FORMULA()",csv_export(result).decode('utf-8-sig'))
        self.assertEqual(result['combined'][0]['company'], "=SYNTHETIC_FORMULA()")

    def test_invalid_selection_and_source_lineage(self):
        for values in ({'tail':'unknown'},{'percent':'nan'},{'percent':51},{'page':0},{'page_size':500},{'path':'secret'}):
            with self.assertRaises(DataError): Selection.from_mapping(values)
        catalog=Catalog(temp/self._testMethodName);catalog.initialize()
        service=ReportService(catalog);prices,ota=service.demo_sources()
        with redirect_stdout(io.StringIO()):
            aid=service.generate(prices,ota,now=self.now)
        actual=service.load(aid)
        self.assertEqual(actual['ranked'],self.result['ranked'])
        self.assertEqual(catalog.inputs(catalog.record(aid)['run_id']),[prices,ota])
        self.assertFalse((catalog.root/'artifacts/scheduler').exists())
