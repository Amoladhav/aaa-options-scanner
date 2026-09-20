"""Offline report parity, large saved universes, privacy and hostile display text."""
from contextlib import redirect_stdout
from copy import deepcopy
import csv
import hashlib
import io
import json
import re
import unittest
from unittest.mock import patch

from offline_boundary import temp
from trading_scanner.cli import main
from trading_scanner.core import DataError
from trading_scanner.ota_report_service import demo_snapshot, generate_report
from trading_scanner.ota_reporting import ReportOptions, build_report, render_console, render_html, write_rows_csv


class OtaReportingTests(unittest.TestCase):
    def setUp(self):
        self.root=temp/self._testMethodName
        self.root.mkdir()
        self.snapshot=demo_snapshot()

    def model(self, snapshot=None, options=ReportOptions()):
        return build_report(snapshot or self.snapshot,'a'*64,generated_at='2026-09-20T15:00:00+00:00',options=options)

    def test_profile_and_raw_types_preserved_without_ranking(self):
        before=deepcopy(self.snapshot)
        model=self.model()
        self.assertEqual(self.snapshot,before)
        self.assertEqual(model['rows'],self.snapshot['rows'])
        self.assertEqual(model['summary']['rows'],24)
        self.assertEqual(model['summary']['mixed_type_fields'],1)
        self.assertEqual(model['summary']['negative_values'],1)
        self.assertEqual(model['summary']['null_cells'],1)
        self.assertIn('volume',model['absent_display_fields'])
        self.assertNotIn('score',model['rows'][0])
        self.assertEqual(model['rows'][1]['values']['meanIvPcnt'],-1)
        self.assertEqual(model['rows'][4]['values']['meanIvPcnt'],'35.5')

    def test_export_keeps_all_5642_rows_and_unknown_fields(self):
        self.snapshot['rows']=[{'symbol':f'S{i}','values':{'meanIvPcnt':-1 if i%2 else '','unfamiliar':{'nested':[i,None]}}} for i in range(5642)]
        self.snapshot['pages_received']=57
        model=self.model(options=ReportOptions(console_rows=2,page_size=50))
        write_rows_csv(model,self.root/'rows.csv')
        with (self.root/'rows.csv').open(newline='') as stream:
            rows=list(csv.DictReader(stream))
        self.assertEqual(len(rows),5642)
        self.assertEqual(json.loads(rows[-1]['values.unfamiliar']),{'nested':[5641,None]})
        html=render_html(model)
        embedded=re.search(r'<script type="application/json" id="data">(.*?)</script>',html,re.S).group(1)
        table=json.loads(embedded)
        self.assertEqual(len(table['rows']),5642)
        self.assertEqual(table['pageSize'],50)
        preview=render_console(model)
        self.assertIn('2/5642',preview)
        self.assertNotIn('S5641',preview)

    def test_html_csv_and_terminal_escape_hostile_source_text(self):
        bad='</script><img src=x onerror=alert(1)>\x1b[2J\n'
        self.snapshot['rows'][0]['values'].update(sector=bad,industry='=HYPERLINK("synthetic")', extra='@SUM(1)',negative=-2)
        self.snapshot['rows'][0]['values']['<unknown>']=None
        model=self.model()
        html=render_html(model)
        self.assertNotIn('<img src=x',html)
        self.assertIn('\\u003c/script',html)
        self.assertIn('&lt;unknown&gt;',html)
        self.assertNotIn('innerHTML',html)
        self.assertNotIn('fetch(',html)
        self.assertNotIn('\x1b',render_console(model))
        write_rows_csv(model,self.root/'safe.csv')
        with (self.root/'safe.csv').open(newline='') as stream:
            row=next(csv.DictReader(stream))
        self.assertTrue(row['values.industry'].startswith("'="))
        self.assertTrue(row['values.extra'].startswith("'@"))
        self.assertEqual(row['values.negative'],'-2')

    def test_incomplete_invalid_and_duplicate_inputs_are_rejected(self):
        for changes in ({'acquisition_status':'incomplete'},{'representation':'ota_normalized'},{'source':'other'},{'pages_received':'bad'},{'retrieved_at':'2026-09-20T12:00:00'}):
            with self.assertRaises(DataError):
                self.model({**self.snapshot,**changes})
        duplicate=deepcopy(self.snapshot)
        duplicate['rows'].append(duplicate['rows'][0])
        with self.assertRaises(DataError):
            self.model(duplicate)
        for options in ((-1,100),(101,100),(20,0),(True,100)):
            with self.assertRaises(DataError):
                ReportOptions(*options)

    def test_empty_report_is_valid_and_explicit(self):
        empty={**self.snapshot,'rows':[]}
        model=self.model(empty)
        self.assertEqual(model['summary']['rows'],0)
        self.assertIn('0/0',render_console(model))
        self.assertIn('report.json',render_html(model))

    def test_service_complete_bundle_and_sanitized_summary(self):
        source=self.root/'saved.json'
        self.snapshot['profile']='ota'
        self.snapshot['rows'][0]['values']['sector']='synthetic-private-marker'
        raw=(json.dumps(self.snapshot,indent=1)+'\n').encode()
        source.write_bytes(raw)
        output=io.StringIO()
        with patch('trading_scanner.ota_fetch.run_fetch',side_effect=AssertionError('network forbidden')), patch('trading_scanner.token_store.load_token',side_effect=AssertionError('credential read forbidden')), redirect_stdout(output):
            self.assertEqual(generate_report(self.root,source=source,options=ReportOptions(console_rows=1)),0)
        destination=next((self.root/'artifacts/ota-reports').iterdir())
        self.assertEqual({p.name for p in destination.iterdir()},{'source.json','report.json','field-profile.json','rows.csv','ota-symbols.txt','report.html','manifest.json'})
        self.assertEqual((destination/'source.json').read_bytes(),raw)
        self.assertEqual(source.read_bytes(),raw)
        model=json.loads((destination/'report.json').read_text())
        self.assertEqual(model['source_sha256'],hashlib.sha256(raw).hexdigest())
        review=json.loads(next(self.root.glob('artifacts/agent-review/*.json')).read_text())
        self.assertEqual(review['counts']['rows'],24)
        self.assertIsNone(review['error_code'])
        self.assertNotIn('synthetic-private-marker',json.dumps(review))
        for path in self.root.glob('artifacts/logs/*'):
            self.assertNotIn('synthetic-private-marker',path.read_text())
        self.assertIn('synthetic-private-marker'[:20],output.getvalue())

    def test_demo_cli_and_missing_live_input_never_fallback(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(['ota-report-demo','--console-rows','0'],self.root),0)
            self.assertEqual(main(['ota-report'],self.root),1)
        reports=list(self.root.glob('artifacts/ota-reports/*/manifest.json'))
        self.assertEqual(len(reports),1)
        summaries=[json.loads(p.read_text()) for p in self.root.glob('artifacts/agent-review/*.json')]
        self.assertTrue(any(r['error_code']=='OTA_REPORT_INPUT_MISSING' for r in summaries))

    def test_latest_uses_only_finished_results_and_no_old_fallback_for_bad_input(self):
        saved=self.root/'artifacts/ota/finished/results.json'
        saved.parent.mkdir(parents=True)
        saved.write_text(json.dumps(self.snapshot))
        pending=self.root/'artifacts/ota/pending/capture.json'
        pending.parent.mkdir(parents=True)
        pending.write_text('{"acquisition_status":"incomplete"}')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(generate_report(self.root),0)
            self.assertEqual(generate_report(self.root,source=pending),1)
        self.assertEqual(len(list(self.root.glob('artifacts/ota-reports/*/manifest.json'))),1)

    def test_output_failure_leaves_no_published_bundle(self):
        source=self.root/'saved.json'
        source.write_text(json.dumps(self.snapshot))
        with patch('trading_scanner.ota_report_service.write_rows_csv',side_effect=OSError('synthetic-private-marker')), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(generate_report(self.root,source=source),1)
        folders=list((self.root/'artifacts/ota-reports').iterdir())
        self.assertTrue(all(p.name.endswith('.pending') for p in folders))
        self.assertNotIn('synthetic-private-marker',output.getvalue())
        report=json.loads(next(self.root.glob('artifacts/agent-review/*.json')).read_text())
        self.assertEqual(report['error_code'],'OTA_REPORT_FAILED')
