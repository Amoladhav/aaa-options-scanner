"""Synthetic selection semantics and exact watchlist/CSV membership."""
from copy import deepcopy
import csv
import io
import unittest

from trading_scanner.core import DataError
from trading_scanner.report_selection import (ColumnFilter, Selection, select_rows,
    watchlist_export, report_columns, number)
from trading_scanner.report_service import csv_export


class ReportSelectionTests(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(symbol=s, group='stock', company='Synthetic', score=i,
                          percentile=i/10, ivGauge=g, tradier_call_bid=bid,
                          ota_raw_values={'custom': bid}, **{'ota_raw.custom': str(bid)})
                     for i, (s, g, bid) in enumerate([
                         ('AAA', 1, '10'), ('BBB', 2, 2), ('CCC', 1, '2.00'),
                         ('DDD', None, None), ('EEE', 10, 'N/A'), ('FFF', 0, '')])]
        self.result = {'combined': self.rows, 'ota_raw_fields': ['custom']}

    def symbols(self, **kw):
        return [r['symbol'] for r in select_rows(self.result, Selection(**kw))]

    def test_every_column_selectable_and_mixed_sort_deterministic(self):
        for field in report_columns(self.result):
            self.assertEqual(len(select_rows(self.result, Selection(sort=field))), 6)
        self.assertEqual(self.symbols(sort='tradier_call_bid', direction='asc'), ['BBB','CCC','AAA','EEE','DDD','FFF'])
        self.assertEqual(self.symbols(sort='tradier_call_bid', direction='desc'), ['AAA','BBB','CCC','EEE','DDD','FFF'])
        self.assertEqual(self.symbols(sort='ota_raw.custom', direction='asc'), ['BBB','CCC','AAA','EEE','DDD','FFF'])

    def test_rules_intersect_existing_controls_without_mutation(self):
        before=deepcopy(self.result)
        rules=(ColumnFilter('ivGauge','eq','1'), ColumnFilter('tradier_call_bid','ge','2'),
               ColumnFilter('company','contains','SYNTH'))
        self.assertEqual(self.symbols(filters=rules,sort='symbol',direction='asc'), ['AAA','CCC'])
        self.assertEqual(self.symbols(filters=rules,tail='bottom',percent=10), ['AAA'])
        self.assertEqual(self.symbols(filters=rules,search='ccc'), ['CCC'])
        self.assertEqual(self.symbols(filters=rules,group='etf'), [])
        self.assertEqual(self.result,before)

    def test_presence_and_raw_lineage_do_not_confuse_markers(self):
        samples=[{}, {'x':None}, {'x':''}, {'x':'  '}, {'x':'null'}, {'x':'[missing]'}, {'x':0}, {'x':False}]
        for field in ('x','ota_raw.x'):
            rows=samples if field=='x' else [{'ota_raw_values':s,'ota_raw.x':'misleading display'} for s in samples]
            expected={'missing':[0], 'null':[1], 'blank':[2,3], 'present':[4,5,6,7]}
            for op,indices in expected.items():
                self.assertEqual([i for i,r in enumerate(rows) if ColumnFilter(field,op).matches(r)],indices)
            self.assertFalse(ColumnFilter(field,'ne','2').matches(rows[0]))
            self.assertFalse(ColumnFilter(field,'not_contains','x').matches(rows[1]))
            self.assertFalse(ColumnFilter(field,'gt','-1').matches(rows[7]))

    def test_numeric_and_text_operators(self):
        for op,term,want in [('eq','2',True),('ne','2',False),('gt','1.5',True),('ge','2',True),('lt','2',False),('le','2',True)]:
            self.assertEqual(ColumnFilter('x',op,term).matches({'x':'2.00'}),want)
        self.assertTrue(ColumnFilter('x','not_contains','ABC').matches({'x':'def'}))
        self.assertTrue(ColumnFilter('x','contains','true').matches({'x':True}))
        self.assertTrue(ColumnFilter('x','contains','delta').matches({'x':{'delta':.5}}))
        self.assertTrue(ColumnFilter('x','eq','9007199254740993').matches({'x':9007199254740993}))
        for value in (True,None,'nan','inf','1.5 * score','1e99999','1'*129):
            self.assertIsNone(number(value))

    def test_invalid_inputs_fail_closed(self):
        for op,value in [('gt','nan'),('lt','score'),('execute','x'),('null','ignored'),('contains','x'*201)]:
            with self.assertRaises(DataError): ColumnFilter('score',op,value)
        for kwargs in ({'filters':(ColumnFilter('score','gt','1'),)*33}, {'columns':('score','score')}, {'page_size':True}, {'percent':float('nan')}):
            with self.assertRaises(DataError): Selection(**kwargs)
        for kwargs in ({'sort':'unknown'}, {'columns':('unknown',)}, {'filters':(ColumnFilter('unknown'),)}):
            with self.assertRaises(DataError): select_rows(self.result,Selection(**kwargs))

    def test_watchlist_sections_sort_order_csv_parity_and_all_pages(self):
        selected=Selection(sort='symbol',direction='desc',page=2)
        data=watchlist_export(self.result,selected)
        self.assertEqual(data,b'###IV0,FFF,###IV1,CCC,AAA,###IV2,BBB,###IV10,EEE,###IV_UNKNOWN,DDD\n')
        csv_rows=list(csv.DictReader(io.StringIO(csv_export(self.result,selected).decode('utf-8-sig'))))
        exported=[s for s in data.decode().strip().split(',') if not s.startswith('###')]
        self.assertEqual(set(exported),{r['symbol'] for r in csv_rows})
        filtered=Selection(filters=(ColumnFilter('ivGauge','eq','1'),),sort='symbol',direction='asc',page=3)
        self.assertEqual(watchlist_export(self.result,filtered),b'###IV1,AAA,CCC\n')
        self.assertEqual(watchlist_export(self.result,Selection(search='no match')),b'')

    def test_watchlist_invalid_gauges_duplicates_and_delimiter_injection(self):
        for gauge in (True,-1,1.5,'IV1','1e9999',None):
            result={'combined':[dict(self.rows[0],ivGauge=gauge)]}
            self.assertEqual(watchlist_export(result,Selection()),b'###IV_UNKNOWN,AAA\n')
        result={'combined':[dict(self.rows[0],symbol='BRK.B',ivGauge='1.0')]*2}
        self.assertEqual(watchlist_export(result,Selection()),b'###IV1,BRK.B\n')
        for symbol in ('AAA,BBB','AAA\n###IV2','###BAD','AAA\rBBB'):
            with self.assertRaises(DataError):
                watchlist_export({'combined':[dict(self.rows[0],symbol=symbol)]},Selection())
