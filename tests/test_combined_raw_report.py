"""Master-driven CRS plus complete OTA source-field presentation regressions."""
from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime
import csv
import io
import json
import unittest

from offline_boundary import temp
from trading_scanner.cli import main
from trading_scanner.core import calculate
from trading_scanner.demo import make_snapshot
from trading_scanner.dashboard import combine, synthetic_ota, write_dashboard, attach_tradier


class CombinedRawReportTests(unittest.TestCase):
    def setUp(self):
        self.snapshot=make_snapshot()
        typed=synthetic_ota(self.snapshot)
        self.raw={**typed,'schema_version':2,'representation':'ota_raw','acquisition_status':'completed_short_page',
                  'rows':[{'symbol':r['symbol'],'values':{k:v for k,v in r.items() if k!='symbol'}} for r in typed['rows']]}
        self.now=datetime.fromisoformat(typed['retrieved_at'])
        self.root=temp/self._testMethodName

    def test_raw_columns_preserve_values_and_do_not_change_crs_or_master(self):
        values=self.raw['rows'][0]['values']
        values.update(sector='Provider sector',industry='Provider industry',last=12.12345678,
                      meanIvPcnt=-1,volume='',customNested={'items':[None,'x']})
        before=deepcopy(self.raw)
        result=combine(self.snapshot,self.raw,now=self.now)
        self.assertEqual(result['ranked'],calculate(self.snapshot)['ranked'])
        self.assertEqual(self.raw,before)
        row=next(r for r in result['combined'] if r['symbol']==self.raw['rows'][0]['symbol'])
        self.assertEqual(row['ota_raw_values'],values)
        self.assertEqual(row['ota_raw.meanIvPcnt'],-1)
        self.assertIsNone(row['meanIvPcnt'])
        self.assertEqual(row['ota_raw.volume'],'""')
        self.assertEqual(row['ota_raw.avgVol30d'],'[missing]')
        self.assertEqual(row['ota_raw.last'],12.12345678)
        self.assertNotEqual(row['sector'],'Provider sector')
        self.assertNotEqual(row['adjusted_close'],12.12345678)
        self.assertEqual(json.loads(row['ota_raw.customNested']),values['customNested'])
        absent=next(r for r in result['combined'] if r['symbol']=='S00')
        self.assertEqual(absent['ota_raw_status'],'not_returned')
        self.assertEqual(absent['ota_raw.last'],'[not returned]')

    def test_comprehensive_ota_does_not_expand_the_master_or_hide_exclusions(self):
        self.raw['rows'] += [{'symbol':f'X{i}','values':{'onlyOutside':i}} for i in range(5642-len(self.raw['rows']))]
        del self.snapshot['prices']['S01']
        result=combine(self.snapshot,self.raw,now=self.now)
        self.assertEqual(len(result['combined']),60)
        self.assertEqual(result['ota_join_counts'],{'received':5642,'matched':48,'outside_master':5594})
        row=next(r for r in result['combined'] if r['symbol']=='S01')
        self.assertEqual(row['crs_status'],'excluded')
        self.assertEqual(row['ota_raw_status'],'captured')
        self.assertIsNone(row['score'])
        self.assertIn('onlyOutside',result['ota_raw_fields'])
        self.assertEqual(row['ota_raw.onlyOutside'],'[missing]')

    def test_legacy_typed_input_marks_raw_unavailable_without_fabrication(self):
        result=combine(self.snapshot,synthetic_ota(self.snapshot),now=self.now)
        row=next(r for r in result['combined'] if r['symbol']=='S01')
        self.assertEqual(row['ota_raw_status'],'not_captured')
        self.assertEqual(row['ota_raw.meanIvPcnt'],'[not captured]')
        self.assertIsNotNone(row['meanIvPcnt'])

    def test_csv_and_html_include_crs_and_all_fields_with_safe_excel_text(self):
        self.raw['rows'][0]['values'].update(industry='=SUM(1)',custom='<script>synthetic</script>',
                                           last=12.12345678, sector='Café', volume=None)
        result=combine(self.snapshot,self.raw,now=self.now)
        attach_tradier(result,[])
        write_dashboard(result,self.root)
        content=(self.root/'master.csv').read_bytes()
        self.assertTrue(content.startswith(b'\xef\xbb\xbf'))
        self.assertEqual(content,(self.root/'combined.csv').read_bytes())
        with (self.root/'master.csv').open(encoding='utf-8-sig',newline='') as stream:
            reader=csv.DictReader(stream)
            rows=list(reader)
            self.assertEqual(len(reader.fieldnames),len(set(reader.fieldnames)))
        self.assertEqual(len(rows),60)
        row=next(r for r in rows if r['symbol']=='S01')
        self.assertEqual(row['ota_raw.industry'],"'=SUM(1)")
        self.assertEqual(row['ota_raw.volume'],'null')
        self.assertEqual(row['ota_raw.sector'],'Café')
        self.assertEqual(row['ota_raw.last'],'12.12345678')
        self.assertEqual(float(row['r21']),next(r for r in result['combined'] if r['symbol']=='S01')['r21'])
        html=(self.root/'dashboard.html').read_text()
        self.assertIn('21-session return',html)
        self.assertIn('OTA raw · custom',html)
        self.assertIn('12.12345678',html)
        self.assertNotIn('<script>synthetic</script>',html)
        self.assertIn('&lt;script&gt;synthetic&lt;/script&gt;',html)

    def test_html_tail_controls_receive_full_precision_percentiles(self):
        from html.parser import HTMLParser
        class Rows(HTMLParser):
            def __init__(self):
                super().__init__()
                self.percentiles=[]
            def handle_starttag(self, tag, attrs):
                data=dict(attrs)
                if tag=='tr' and 'data-percentile' in data:
                    self.percentiles.append(data['data-percentile'])
        del self.snapshot['prices']['S01']
        result=combine(self.snapshot,self.raw,now=self.now)
        attach_tradier(result,[])
        write_dashboard(result,self.root)
        html=(self.root/'dashboard.html').read_text()
        parser=Rows()
        parser.feed(html)
        self.assertEqual(parser.percentiles,[str(r['percentile']) if r.get('percentile') is not None else '' for r in result['combined']])
        self.assertIn('',parser.percentiles)
        for x in (.1,.2,.5):
            top=[float(p) for p in parser.percentiles if p and float(p)>=1-x]
            bottom=[float(p) for p in parser.percentiles if p and float(p)<=x]
            self.assertTrue(top)
            self.assertTrue(bottom)
            self.assertTrue(all(p>=1-x for p in top))
        self.assertIn('id="tailPercent" required type="number"',html)
        self.assertIn('Short research: bottom X%',html)
        self.assertIn('Tradier rows attached: 0 / 60',html)
        self.assertIn('What are OTA field diagnostics?',html)

    def test_cli_demo_preserves_source_and_prints_excel_paths(self):
        output=io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(['dashboard-demo'],self.root),0)
        folder=next(self.root.glob('artifacts/dashboards/synthetic/*'))
        source=json.loads((folder/'ota-input.json').read_text())
        self.assertEqual(source['representation'],'ota_raw')
        self.assertIn('customExample',source['rows'][0]['values'])
        self.assertIn('Excel CSV (all master rows):',output.getvalue())
        review=json.loads(next(self.root.glob('artifacts/agent-review/*.json')).read_text())
        self.assertEqual(review['counts']['ota_received'],48)
        self.assertNotIn('customExample',json.dumps(review))
        self.assertNotIn('S01',json.dumps(review))
