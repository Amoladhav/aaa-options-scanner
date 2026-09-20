"""Expression truth tables, type/size boundaries, migration and export parity."""
from copy import deepcopy
from decimal import localcontext
import csv
import io
import itertools
import json
import unittest

from trading_scanner.core import DataError
from trading_scanner.report_expressions import (
    compile_expression, encode_document, decode_document, empty_document,
    edit_expression, expression_for_selection, expression_summary, MAX_EXPRESSION_BYTES)
from trading_scanner.report_selection import ColumnFilter, Selection, select_rows, watchlist_export
from trading_scanner.report_service import csv_export


def literal(field='score', op='gt', value='0'):
    return {'type':'literal','field':field,'op':op,'value':value}


def column(field='meanIvPcnt', op='gt', other='ivLow1YrPcnt', factor='1.5'):
    return {'type':'column','field':field,'op':op,'other':other,'factor':factor}


def group(kind, *rules):
    return {'type':kind,'rules':list(rules)}


def document(root):
    return encode_document({'version':1,'root':root})


class ExpressionTests(unittest.TestCase):
    def test_nested_truth_table_and_explicit_precedence(self):
        a,b,c=literal('score'),literal('r21'),literal('ivGauge','eq','1')
        first=compile_expression(document(group('any',group('all',a,b),c)))
        second=compile_expression(document(group('all',a,group('any',b,c))))
        for x,y,z in itertools.product((0,1),repeat=3):
            row={'score':x,'r21':y,'ivGauge':z}
            self.assertEqual(first.matches(row),bool((x and y) or z))
            self.assertEqual(second.matches(row),bool(x and (y or z)))
        self.assertIn(' OR ',expression_summary(document(group('any',group('all',a,b),c))))

    def test_cross_column_decimal_precision_and_all_comparisons(self):
        for op,want in [('gt',False),('ge',True),('eq',True),('ne',False),('lt',False),('le',True)]:
            rule=compile_expression(document(group('all',column(op=op))))
            self.assertEqual(rule.matches({'meanIvPcnt':'0.3','ivLow1YrPcnt':'0.2'}),want)
        rule=compile_expression(document(group('all',column(factor='1.00000000000000000000000000001'))))
        with localcontext() as context:
            context.prec=2
            self.assertTrue(rule.matches({'meanIvPcnt':'1.00000000000000000000000000002','ivLow1YrPcnt':'1'}))
        rule=compile_expression(document(group('all',column(factor='-2'))))
        self.assertTrue(rule.matches({'meanIvPcnt':-1,'ivLow1YrPcnt':1}))

    def test_missing_null_blank_boolean_non_numeric_and_zero_factor(self):
        for op in ('eq','ne','gt','ge','lt','le'):
            rule=compile_expression(document(group('all',column(op=op,factor='0'))))
            for bad in (None,True,False,'','  ','nan','inf','not a number',{},[]):
                self.assertFalse(rule.matches({'meanIvPcnt':bad,'ivLow1YrPcnt':1}))
                self.assertFalse(rule.matches({'meanIvPcnt':1,'ivLow1YrPcnt':bad}))
            self.assertFalse(rule.matches({}))
        rule=compile_expression(document(group('any',column(),literal('ivLow1YrPcnt','null',''))))
        self.assertTrue(rule.matches({'ivLow1YrPcnt':None}))

    def test_units_known_unknown_percent_scales_and_raw_lineage(self):
        for a,b in [('meanIvPcnt','r21'),('percentile','r21'),('ivGauge','ivGauge'),
                    ('ota_raw.unknown','ota_raw.unknown'),('totalOptionsVolume','avgVol30d'),
                    ('tradier_call_spread_pct','r21')]:
            with self.assertRaisesRegex(DataError,'REPORT_EXPRESSION_UNITS'):
                compile_expression(document(group('all',column(a,other=b))))
        for a,b in [('r21','r63'),('meanIvPcnt','ota_raw.ivHi1YrPcnt'),
                    ('tradier_call_bid','tradier_call_ask'),('totalOptionsVolume','tradier_call_volume')]:
            compile_expression(document(group('all',column(a,other=b))))
        raw=compile_expression(document(group('all',column('ota_raw.meanIvPcnt',other='ota_raw.ivLow1YrPcnt'))))
        self.assertTrue(raw.matches({'ota_raw_values':{'meanIvPcnt':'30','ivLow1YrPcnt':'10'},'ota_raw.meanIvPcnt':'wrong display'}))
        self.assertFalse(raw.matches({'ota_raw.meanIvPcnt':30,'ota_raw.ivLow1YrPcnt':10}))

    def test_all_legacy_operators_migrate_without_changing_membership(self):
        rows=[{'symbol':str(i),'group':'stock','score':v} for i,v in enumerate((None,'',1,'2','abc',False))]
        rows.append({'symbol':'absent','group':'stock'})
        result={'combined':rows}
        for op,value in [('eq','2'),('ne','2'),('contains','a'),('not_contains','a'),
                         ('gt','1'),('ge','1'),('lt','1'),('le','1'),('missing',''),('null',''),('blank',''),('present','')]:
            old=Selection(filters=(ColumnFilter('score',op,value),))
            new=Selection(expression=expression_for_selection(old))
            self.assertEqual(select_rows(result,old),select_rows(result,new))
        # Largest supported old text terms still migrate; do not narrow C3a's
        # contract merely because the versioned representation adds overhead.
        old=Selection(filters=(ColumnFilter('company','contains','x'*200),)*32)
        new=Selection(expression=expression_for_selection(old))
        self.assertEqual(select_rows(result,old),select_rows(result,new))

    def test_combined_old_new_rules_are_and_and_bounded_together(self):
        expr=document(group('any',literal('score'),literal('ivGauge','eq','1')))
        selected=Selection(filters=(ColumnFilter('group','eq','etf'),),expression=expr)
        result={'combined':[{'symbol':'AAA','group':'stock','score':1,'ivGauge':1},
                            {'symbol':'BBB','group':'etf','score':1,'ivGauge':1}]}
        self.assertEqual([r['symbol'] for r in select_rows(result,selected)],['BBB'])
        with self.assertRaises(DataError):
            Selection(filters=(ColumnFilter('score','gt','0'),)*32,expression=expr)

    def test_structural_and_version_validation(self):
        samples=['not JSON','{"version":1,"version":1,"root":{}}','{"version":NaN,"root":{}}',
                 json.dumps({'version':True,'root':group('all')}),json.dumps({'version':2,'root':group('all')}),
                 json.dumps({'version':1,'root':group('all'),'extra':0}),document(group('all',{'type':'not','rules':[]})),
                 document(group('any')),document(group('all',group('all'))),
                 document(group('all',dict(literal(),extra='x'))),document(group('all',dict(literal(),field=''))),
                 document(group('all',literal('company','contains','\ud800')))]
        for text in samples:
            with self.assertRaises(DataError,msg=text): compile_expression(text)
        self.assertTrue(compile_expression(document(group('all'))).matches({}))
        with self.assertRaises(DataError): compile_expression(document(group('all',literal('unknown'))),{'score'})

    def test_bounds_and_injection_inputs(self):
        for factor in ('nan','inf','1e9999','1000001','-1000001','1'*33,'1.5 * score','__import__("os")'):
            with self.assertRaises(DataError): compile_expression(document(group('all',column(factor=factor))))
        for op in ('contains','execute','missing'):
            with self.assertRaises(DataError): compile_expression(document(group('all',column(op=op))))
        with self.assertRaises(DataError): compile_expression(' '*(MAX_EXPRESSION_BYTES+1))
        with self.assertRaises(DataError): compile_expression('['*1000+']'*1000)
        with self.assertRaises(DataError): compile_expression(document(group('all',*[literal()]*33)))
        nested=literal()
        for _ in range(5): nested=group('all',nested)
        with self.assertRaises(DataError): compile_expression(document(nested))

    def test_editor_draft_operations_preserve_input_and_validate_paths(self):
        start=encode_document(empty_document())
        draft=edit_expression(start,{},'add_group:r')
        draft=edit_expression(draft,{},'add_rule:r.0')
        self.assertEqual(decode_document(start),empty_document())
        with self.assertRaises(DataError): compile_expression(draft)
        draft=edit_expression(draft,{'e.r.0.type':'any','e.r.0.0.field':'score','e.r.0.0.op':'ge','e.r.0.0.value':'0'},'apply')
        self.assertTrue(compile_expression(draft).matches({'score':0}))
        cross=edit_expression(draft,{'e.r.0.0.type':'column','e.r.0.0.field':'meanIvPcnt',
                                   'e.r.0.0.other':'ivLow1YrPcnt','e.r.0.0.factor':'1.5'},'apply')
        self.assertTrue(compile_expression(cross).matches({'meanIvPcnt':30,'ivLow1YrPcnt':10}))
        cleared=edit_expression(cross,{},'remove:r.0')
        self.assertEqual(decode_document(cleared),empty_document())
        self.assertEqual(edit_expression(draft,{},'clear'),start)
        for action in ('remove:r','add_rule:../../x','add_rule:r.9','add_rule:r.0.0','unknown:r'):
            with self.assertRaises(DataError): edit_expression(draft,{},action)
        with self.assertRaises(DataError): edit_expression(draft,{'e.r.5.field':'score'},'apply')

    def test_csv_watchlist_and_table_match_across_pages_without_mutation(self):
        rows=[{'symbol':f'S{i:02}','group':'stock','score':i,'ivGauge':i%3,
               'meanIvPcnt':i,'ivLow1YrPcnt':10} for i in range(60)]
        result={'combined':rows};before=deepcopy(result)
        expr=document(group('all',column(),group('any',literal('ivGauge','eq','1'),literal('ivGauge','eq','2'))))
        selected=Selection(expression=expr,page=2,sort='symbol',direction='asc')
        expected=[r['symbol'] for r in rows if r['meanIvPcnt']>15 and r['ivGauge'] in (1,2)]
        self.assertEqual([r['symbol'] for r in select_rows(result,selected)],expected)
        exported=list(csv.DictReader(io.StringIO(csv_export(result,selected).decode('utf-8-sig'))))
        self.assertEqual([r['symbol'] for r in exported],expected)
        watch=[s for s in watchlist_export(result,selected).decode().strip().split(',') if not s.startswith('###')]
        self.assertEqual(set(watch),set(expected))
        self.assertGreater(len(watch),25)
        self.assertEqual(result,before)
        self.assertEqual(Selection.from_mapping(dict(selected.query())).expression,expr)
