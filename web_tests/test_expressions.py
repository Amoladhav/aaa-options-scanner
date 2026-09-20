"""Exercise the server-rendered editor by submitting its actual form controls."""
from contextlib import redirect_stdout
from html import unescape
from html.parser import HTMLParser
import csv
import io
import re
import unittest
from urllib.parse import urlencode, urlsplit, parse_qs
from unittest.mock import patch

from offline_boundary import temp
from trading_scanner.catalog import Catalog
from trading_scanner.catalog import encoded
from trading_scanner.report_service import ReportService
from trading_scanner.report_expressions import encode_document, empty_document
from trading_scanner.web import create_app

BASE='http://127.0.0.1:8765'


class EditorForm(HTMLParser):
    def __init__(self,html):
        super().__init__()
        self.active=False;self.controls=[];self.select=None;self.options=[]
        self.feed(html)

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='form':
            self.active=attrs.get('class')=='expression-form'
        if not self.active:
            return
        if tag=='input' and attrs.get('name'):
            self.controls.append((attrs['name'],attrs.get('value','')))
        if tag=='select':
            self.select=attrs['name'];self.options=[]
        if tag=='option':
            self.options.append((attrs.get('value',''),'selected' in attrs))

    def handle_endtag(self,tag):
        if tag=='select' and self.active:
            value=next((value for value,selected in self.options if selected),self.options[0][0])
            self.controls.append((self.select,value));self.select=None
        if tag=='form':
            self.active=False


class ExpressionRoutesTests(unittest.TestCase):
    def setUp(self):
        self.catalog=Catalog(temp/self._testMethodName);self.catalog.initialize()
        self.service=ReportService(self.catalog)
        self.output=self.enterContext(redirect_stdout(io.StringIO()))
        prices,ota=self.service.demo_sources()
        self.aid=self.service.generate(prices,ota)
        self.client=create_app(self.catalog).test_client()
        self.path='/reports/'+self.aid

    def get(self,path):
        return self.client.get(path,base_url=BASE)

    def edit(self,response,action,changes=None):
        changes=changes or {}
        form=EditorForm(response.text)
        self.assertTrue(form.controls)
        pairs=[(key,changes.get(key,value)) for key,value in form.controls]
        self.assertFalse(set(changes)-{key for key,_ in pairs})
        return self.get(self.path+'?'+urlencode(pairs+[('action',action)]))

    def links(self,response):
        return [unescape(link) for link in re.findall('href="([^"]+)"',response.text)]

    def exported(self,response):
        link=next(link for link in self.links(response) if 'scope=filtered' in link)
        download=self.get(link)
        self.assertEqual(download.status_code,200)
        return list(csv.DictReader(io.StringIO(download.data.decode('utf-8-sig'))))

    def test_actual_builder_nested_group_apply_exports_and_draft_isolation(self):
        before=len(self.catalog.runs())
        with patch('trading_scanner.credentials.resolve',side_effect=AssertionError('denied')),patch('trading_scanner.ota_fetch.run_fetch',side_effect=AssertionError('denied')):
            page=self.get(self.path+'?page=2&sort=symbol&direction=asc&column=symbol&column=ivGauge')
            page=self.edit(page,'add_rule:r')
            self.assertEqual(page.status_code,200)
            self.assertIn('Draft changes are not applied',page.text)
            self.assertIn('Page 2',page.text)
            self.assertEqual(len(self.exported(page)),60)
            page=self.edit(page,'add_group:r',{'e.r.0.field':'meanIvPcnt','e.r.0.type':'column',
                'e.r.0.op':'gt','e.r.0.other':'ivLow1YrPcnt','e.r.0.factor':'3'})
            page=self.edit(page,'add_rule:r.1',{'e.r.1.type':'any'})
            page=self.edit(page,'add_rule:r.1',{'e.r.1.0.field':'ivGauge','e.r.1.0.value':'1'})
            page=self.edit(page,'apply',{'e.r.1.1.field':'ivGauge','e.r.1.1.value':'2'})
            self.assertEqual(page.status_code,200)
            self.assertIn('Page 1',page.text)
            self.assertIn(' OR ',page.text)
            self.assertIn(' AND ',page.text)
            self.assertIn('3 × ivLow1YrPcnt',page.text)
            rows=self.service.load(self.aid)['combined']
            expected=sorted(r['symbol'] for r in rows if r['meanIvPcnt'] is not None and r['meanIvPcnt']>3*r['ivLow1YrPcnt'] and r['ivGauge'] in (1,2))
            self.assertEqual([r['symbol'] for r in self.exported(page)],expected)
            watch=next(link for link in self.links(page) if '/watchlist?' in link)
            symbols=[s for s in self.get(watch).text.strip().split(',') if not s.startswith('###')]
            self.assertEqual(set(symbols),set(expected))
            # Draft removal cannot broaden the exported selection before Apply.
            draft=self.edit(page,'remove:r.0')
            self.assertEqual([r['symbol'] for r in self.exported(draft)],expected)
            discard=next(link for link in self.links(draft) if 'draft' not in link and parse_qs(urlsplit(link).query).get('column')==['symbol','ivGauge'] and '/export' not in link and '/watchlist' not in link and 'expression=' in link)
            self.assertEqual(self.get(discard).status_code,200)
            page=self.edit(draft,'clear')
            self.assertEqual(len(self.exported(page)),60)
        self.assertEqual(len(self.catalog.runs()),before)

    def test_invalid_apply_retains_applied_selection_and_safe_feedback(self):
        page=self.get(self.path+'?field=ivGauge&op=eq&value=1')
        old=[r['symbol'] for r in self.exported(page)]
        page=self.edit(page,'apply',{'e.r.0.type':'column','e.r.0.field':'meanIvPcnt','e.r.0.op':'gt',
                                    'e.r.0.other':'r21','e.r.0.factor':'1.5'})
        self.assertEqual(page.status_code,400)
        self.assertIn('matching documented units',page.text)
        self.assertEqual([r['symbol'] for r in self.exported(page)],old)
        page=self.edit(page,'apply',{'e.r.0.other':'ivLow1YrPcnt','e.r.0.factor':'__import__("os")'})
        self.assertEqual(page.status_code,400)
        self.assertIn('multiplier must be a finite number',page.text)
        self.assertEqual([r['symbol'] for r in self.exported(page)],old)
        page=self.edit(page,'apply',{'e.r.0.factor':'1.5'})
        self.assertEqual(page.status_code,200)

    def test_editor_and_expression_query_boundaries_and_escaping(self):
        expr=encode_document({'version':1,'root':{'type':'all','rules':[
            {'type':'literal','field':'company','op':'contains','value':'<script>synthetic</script>'}]}})
        page=self.get(self.path+'?'+urlencode({'expression':expr}))
        self.assertEqual(page.status_code,200)
        self.assertNotIn('<script>synthetic</script>',page.text)
        self.assertIn('&lt;script&gt;',page.text)
        for args in ({'expression':'{}'}, {'expression':'['*1000+']'*1000},
                     {'e.r.0.field':'score'}, {'action':'apply'}, {'draft':encode_document(empty_document())},
                     {'draft':encode_document(empty_document()),'action':'add_rule:../../private-marker'},
                     {'draft':encode_document(empty_document()),'action':'apply','e.r.99.field':'private-marker'}):
            response=self.get(self.path+'?'+urlencode(args))
            self.assertEqual(response.status_code,400)
            self.assertNotIn('private-marker',response.text)
        for suffix in ('/watchlist','/export?scope=filtered&'):
            url=self.path+suffix+('' if '?' in suffix else '?')+urlencode({'draft':encode_document(empty_document()),'action':'clear'})
            self.assertEqual(self.get(url).status_code,400)
        self.assertEqual(self.get(self.path+'?expression=x&expression=y').status_code,400)

    def test_full_rule_budget_and_600_row_report_export(self):
        result=self.service.load(self.aid)
        originals=result['combined']
        result['combined']=[dict(row,symbol=f'X{i:02}{row["symbol"]}') for i in range(10) for row in originals]
        aid=self.catalog.publish(encoded(result),kind='report',profile='synthetic')
        expr=encode_document({'version':1,'root':{'type':'all','rules':[
            {'type':'literal','field':'score','op':'gt','value':'-100'} for _ in range(32)]}})
        path='/reports/'+aid
        page=self.get(path+'?'+urlencode({'expression':expr,'page':2}))
        self.assertEqual(page.status_code,200)
        self.assertIn('600 selected',page.text)
        self.assertIn('name="e.r.31.field"',page.text)
        export=next(link for link in self.links(page) if 'scope=filtered' in link)
        parsed=list(csv.DictReader(io.StringIO(self.get(export).data.decode('utf-8-sig'))))
        self.assertEqual(len(parsed),600)
        self.path=path
        excessive=self.edit(page,'add_rule:r')
        self.assertEqual(excessive.status_code,400)
        self.assertIn('at most 32 rules',excessive.text)
        self.assertEqual(len(self.exported(excessive)),600)
