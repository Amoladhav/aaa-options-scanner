from contextlib import redirect_stdout
from copy import deepcopy
from datetime import datetime
import csv
import io
import json
import re
import unittest
from urllib.parse import urlencode, urlsplit, parse_qs
from html import unescape
from unittest.mock import patch,Mock
from offline_boundary import temp
from trading_scanner.catalog import Catalog,encoded
from trading_scanner.demo import make_snapshot
from trading_scanner.dashboard import synthetic_ota
from trading_scanner.report_service import ReportService,compose_report,csv_export
from trading_scanner.report_selection import Selection, ColumnFilter, watchlist_export
from trading_scanner.report_expressions import decode_document
from trading_scanner.web import create_app
from trading_scanner.core import DataError

BASE='http://127.0.0.1:8765'

class WebRoutesTests(unittest.TestCase):
    def setUp(self):
        self.catalog=Catalog(temp/self._testMethodName);self.catalog.initialize()
        self.service=ReportService(self.catalog)
        self.prices,self.ota=self.service.demo_sources()
        self.app=create_app(self.catalog);self.client=self.app.test_client()
        self.output=self.enterContext(redirect_stdout(io.StringIO()))

    def get(self,path='/',**kw):
        return self.client.get(path,base_url=BASE,**kw)

    def csrf(self):
        response=self.get()
        self.assertEqual(response.status_code,200)
        return re.search('name="csrf" value="([a-f0-9]+)"',response.text).group(1)

    def post(self,data,**kw):
        return self.client.post('/reports',base_url=BASE,data=data,headers={'Origin':BASE},**kw)

    def report(self):
        response=self.post({'csrf':self.csrf(),'prices':self.prices,'ota':self.ota})
        self.assertEqual(response.status_code,303,response.text)
        return response.headers['Location']

    def test_imported_history_label_and_export_survive_rollback(self):
        from trading_scanner.core import calculate
        from trading_scanner.dashboard import save_history
        from trading_scanner.legacy_history import LegacyHistory
        snapshot = make_snapshot()
        old = deepcopy(snapshot)
        old['sessions'] = old['sessions'][:-1]
        old['as_of'] = old['membership_observed_at'] = old['sessions'][-1]
        save_history(self.catalog.root/'artifacts/history/synthetic', calculate(old))
        legacy = LegacyHistory(self.catalog)
        batch = legacy.apply('synthetic', legacy.preview('synthetic')['preview_id'])
        path = self.report()
        self.assertIn('Prior ranks use imported legacy history', self.get(path).text)
        exported = self.get(path+'/export?scope=full')
        self.assertEqual(exported.status_code, 200)
        legacy.rollback(batch['batch_id'])
        self.assertEqual(self.get(path+'/export?scope=full').data, exported.data)
        self.assertEqual(self.get(path).status_code, 200)
        self.assertIn('Prior ranks use imported legacy history', self.get(path).text)

    def test_setup_page_never_reads_credentials_or_accepts_secret_posts(self):
        with patch('trading_scanner.token_store.operate',side_effect=AssertionError('store denied')), patch('trading_scanner.credentials.resolve',side_effect=AssertionError('credentials denied')):
            response=self.get('/settings')
            self.assertEqual(response.status_code,200)
            self.assertIn('credential-manage add',response.text)
            self.assertIn('SCANNER_TRADIER_SANDBOX_TOKEN',response.text)
            self.assertNotIn('type="password"',response.text)
        response=self.client.post('/settings',base_url=BASE,data={'csrf':self.csrf(),'value':'synthetic-private-marker'},headers={'Origin':BASE})
        self.assertEqual(response.status_code,405)
        self.assertNotIn('synthetic-private-marker',response.text)

    def test_saved_screener_flow_conflict_and_historical_apply(self):
        from trading_scanner.workspace_settings import WorkspaceSettings,selection_payload
        path=self.report();aid=path.rsplit('/',1)[-1]
        def save(expected='',name='My screener',tail='top'):
            return self.client.post('/screeners',base_url=BASE,headers={'Origin':BASE},data={
                'csrf':self.csrf(),'report':aid,'expected':expected,'name':name,
                'selection':json.dumps(selection_payload(Selection(tail=tail)))})
        response=save();self.assertEqual(response.status_code,303)
        first=response.headers['Location'].rsplit('/',1)[-1]
        self.assertIn('My screener',self.get('/screeners').text)
        self.assertEqual(save().status_code,409)
        self.assertEqual(save(first,name='',tail='bottom').status_code,303)
        self.assertEqual(save(first).status_code,409)
        response=self.get(path+'?screener='+first)
        self.assertEqual(response.status_code,200)
        self.assertIn('Saved screeners',response.text)
        self.assertEqual(WorkspaceSettings(self.catalog).apply(first,self.service.load(aid)).tail,'top')
        self.assertEqual(self.get(path+'?screener='+first+'&search=oops').status_code,400)
        self.assertEqual(self.client.post('/screeners',base_url=BASE,data={}).status_code,403)

    def test_preferences_persist_and_explicit_view_overrides_default(self):
        from trading_scanner.workspace_settings import WorkspaceSettings
        response=self.client.post('/preferences',base_url=BASE,headers={'Origin':BASE},data={
            'csrf':self.csrf(),'expected':'','page_size':'50','display_timezone':'utc'})
        self.assertEqual(response.status_code,303)
        path=self.report()
        self.assertEqual(self.get(path).text.count('Fields & diagnostics'),50)
        self.assertEqual(WorkspaceSettings(self.catalog).preference_state()[1]['page_size'],50)
        response=self.get(path+'?page_size=25')
        self.assertEqual(response.status_code,200)
        self.assertIn('Next',response.text)
        self.assertEqual(response.text.count('Fields & diagnostics'),25)
        self.assertEqual(self.client.post('/preferences',base_url=BASE,headers={'Origin':BASE},data={
            'csrf':self.csrf(),'expected':'','page_size':'100','display_timezone':'local'}).status_code,409)
        self.assertIn('Display preferences',self.get('/settings').text)

    def test_health_navigation_and_no_side_effects(self):
        before=len(self.catalog.runs())
        with patch('trading_scanner.credentials.resolve',side_effect=AssertionError('credentials denied')),patch('trading_scanner.ota_fetch.run_fetch',side_effect=AssertionError('providers denied')):
            for path in ('/','/runs','/health','/assets/app.css'):
                response=self.get(path)
                self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(len(self.catalog.runs()),before)
        self.assertEqual(self.get('/health').json,{'status':'ok','schema_version':1,'providers_enabled':False,'scheduling_enabled':False})
        self.assertFalse((self.catalog.root/'artifacts/scheduler').exists())

    def test_csrf_origin_host_proxy_and_loopback(self):
        token=self.csrf();data={'csrf':token,'prices':self.prices}
        for kwargs in ({},{'headers':{'Origin':'https://evil.example'}},{'headers':{'Origin':'null'}}):
            self.assertEqual(self.client.post('/reports',base_url=BASE,data=data,**kwargs).status_code,403)
        self.assertEqual(self.post({'csrf':'incorrect','prices':self.prices}).status_code,403)
        for host in ('http://evil.example:8765','http://localhost:8765','http://127.0.0.1:9999'):
            self.assertIn(self.client.get('/',base_url=host).status_code,(400,403))
        self.assertEqual(self.get(headers={'X-Forwarded-Host':'evil.example'}).status_code,403)
        self.assertEqual(self.get(environ_overrides={'REMOTE_ADDR':'192.0.2.1'}).status_code,403)
        self.assertEqual(self.get(headers={'Sec-Fetch-Site':'cross-site'}).status_code,403)

    def test_report_pagination_and_full_filtered_csv_parity(self):
        path=self.report()
        response=self.get(path)
        self.assertEqual(response.status_code,200,response.text)
        self.assertIn('SYNTHETIC DEMO',response.text)
        self.assertIn('60 selected',response.text)
        self.assertIn('Not attached',response.text)
        result=self.service.load(path.rsplit('/',1)[1])
        self.assertEqual(self.get(path+'/export?scope=full').data,csv_export(result))
        filtered=self.get(path+'/export?scope=filtered&tail=top&percent=10&page=2')
        parsed=list(csv.DictReader(io.StringIO(filtered.data.decode('utf-8-sig'))))
        expected=[r for r in result['combined'] if r.get('percentile',0)>=.9]
        self.assertEqual({r['symbol'] for r in parsed},{r['symbol'] for r in expected})
        page=self.get(path+'?page=2&page_size=25')
        self.assertEqual(page.status_code,200)
        self.assertIn('Page 2',page.text)
        self.assertIn('no-store',response.headers['Cache-Control'])
        self.assertIn("frame-ancestors 'none'",response.headers['Content-Security-Policy'])

    def test_traversal_wrong_kind_invalid_filters_and_no_raw_routes(self):
        token=self.csrf()
        for aid in ('../../config/credentials.json',self.ota,'f'*32):
            self.assertEqual(self.post({'csrf':token,'prices':aid}).status_code,400)
        path=self.report()
        for query in ('percent=nan','page=0','sort=arbitrary','search='+('x'*101),'page=1&page=2','path=/etc/passwd'):
            self.assertEqual(self.get(path+'?'+query).status_code,400)
        for target in ('/artifacts/catalog/catalog.sqlite3','/raw/'+self.ota,'/assets/../../config/credentials.json','/jobs','/schedule'):
            self.assertEqual(self.get(target).status_code,404)
        self.assertEqual(self.get(path+'/export').status_code,400)

    def test_escaping_safe_error_no_environment_or_raw_exceptions(self):
        snapshot=make_snapshot();snapshot['universe'][0]['company']='<script>synthetic-danger</script>'
        price=self.catalog.publish(encoded(snapshot),kind='prices',profile='synthetic')
        response=self.post({'csrf':self.csrf(),'prices':price,'ota':self.ota})
        html=self.get(response.headers['Location']+'?page_size=100').text
        self.assertNotIn('<script>synthetic-danger',html)
        self.assertIn('&lt;script&gt;',html)
        with patch.object(self.catalog,'list_artifacts',side_effect=RuntimeError('synthetic-private-marker')):
            response=self.get()
        self.assertEqual(response.status_code,500)
        self.assertNotIn('synthetic-private-marker',response.text+self.output.getvalue())
        self.assertNotIn(str(self.catalog.root),response.text)

    def test_synthetic_public_format_quotes_failures_and_master_mismatch(self):
        snapshot=make_snapshot();snapshot['profile']='public'
        ota=synthetic_ota(snapshot);ota['source']='ota';ota['coverage']='short_page_observed'
        stamp=ota['retrieved_at']
        result=compose_report(snapshot,ota,now=datetime.fromisoformat(stamp))
        batch={'schema_version':1,'source':'tradier','representation':'tradier_batch','profile':'sandbox',
               'master_id':result['master_id'],'status':'completed_with_errors','started_at':stamp,'rows':[]}
        for index,member in enumerate(snapshot['universe']):
            symbol=member['symbol']
            probe={'schema_version':1,'source':'tradier','profile':'sandbox','symbol':symbol,'retrieved_at':stamp,
                   'atm_strike':100,'expiration':'2026-10-16','expiration_type':'standard',
                   'call':{'strike':100,'bid':2.25,'ask':2.5},'put':{'strike':100,'bid':3.25,'ask':3.5}}
            batch['rows'].append({'symbol':symbol,'status':'returned' if index else 'failed',
                                 'result':probe if index else None,'error_code':None if index else 'TRADIER_SCHEMA_INVALID'})
        price=self.catalog.publish(encoded(snapshot),kind='prices',profile='public')
        source=self.catalog.publish(encoded(ota),kind='ota',profile='ota')
        tradier=self.catalog.publish(encoded(batch),kind='tradier',profile='sandbox')
        response=self.post({'csrf':self.csrf(),'prices':price,'ota':source,'tradier':tradier})
        self.assertEqual(response.status_code,303,response.text)
        page=self.get(response.headers['Location'])
        self.assertEqual(page.status_code,200,page.text)
        self.assertIn('<td>2.25</td><td>2.5</td>',page.text)
        self.assertIn('59',page.text)
        batch['master_id']='f'*64
        bad=self.catalog.publish(encoded(batch),kind='tradier',profile='sandbox')
        self.assertEqual(self.post({'csrf':self.csrf(),'prices':price,'ota':source,'tradier':bad}).status_code,400)

    def test_startup_fixed_loopback_and_cleanup_without_sockets(self):
        from argparse import Namespace
        from trading_scanner.web_cli import run_web
        server=Mock();server.run.side_effect=KeyboardInterrupt()
        with patch('waitress.create_server',return_value=server) as create:
            self.assertEqual(run_web(temp/'web-launch',Namespace(demo=True,port=8765)),130)
        self.assertEqual(create.call_args.kwargs['host'],'127.0.0.1')
        self.assertFalse(create.call_args.kwargs['expose_tracebacks'])
        server.close.assert_called_once()
        with patch('waitress.create_server') as create:
            self.assertEqual(run_web(temp/'web-bad-port',Namespace(demo=True,port=80)),1)
        create.assert_not_called()

    def test_report_history_links_pin_prior_and_survive_same_session_rerun(self):
        snapshot=make_snapshot()
        snapshot['sessions']=snapshot['sessions'][:-1]
        snapshot['as_of']=snapshot['sessions'][-1]
        snapshot['universe']=[r for r in snapshot['universe'] if r['symbol']!='S00']
        price=self.catalog.publish(encoded(snapshot),kind='prices',profile='synthetic',master=snapshot['universe'])
        with redirect_stdout(io.StringIO()):
            prior=self.service.generate(price)
            current=self.service.generate(self.prices,self.ota)
            newer=self.service.generate(price)
        page=self.get('/reports/'+current)
        self.assertEqual(page.status_code,200)
        self.assertIn('/reports/'+prior,page.text)
        self.assertNotIn('/reports/'+newer,page.text)
        self.assertIn('Master membership changed',page.text)
        self.assertEqual(self.service.load(current)['previous_session'],snapshot['as_of'])
        with redirect_stdout(io.StringIO()):
            replay=self.service.replay(current)
        page=self.get('/reports/'+replay)
        self.assertEqual(page.status_code,200)
        self.assertIn('Replayed with the original evaluation time',page.text)
        self.assertIn('/reports/'+current,page.text)

    def test_slow_report_keeps_health_responsive_and_rejects_duplicate_work(self):
        import threading
        started,release=threading.Event(),threading.Event()
        service=Mock()
        def slow(*args):
            started.set()
            if not release.wait(5):
                raise RuntimeError('synthetic timeout')
            return 'a'*32
        service.generate.side_effect=slow
        app=create_app(self.catalog,service=service)
        client=app.test_client()
        response=client.get('/',base_url=BASE)
        csrf=re.search('name="csrf" value="([a-f0-9]+)"',response.text).group(1)
        answers=[]
        worker=threading.Thread(target=lambda:answers.append(client.post('/reports',base_url=BASE,
            data={'csrf':csrf,'prices':self.prices},headers={'Origin':BASE}).status_code))
        worker.start()
        try:
            self.assertTrue(started.wait(3))
            second=app.test_client()
            response=second.get('/',base_url=BASE)
            token=re.search('name="csrf" value="([a-f0-9]+)"',response.text).group(1)
            self.assertEqual(second.get('/health',base_url=BASE).status_code,200)
            self.assertEqual(second.post('/reports',base_url=BASE,data={'csrf':token,'prices':self.prices},headers={'Origin':BASE}).status_code,409)
        finally:
            release.set();worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(answers,[303])
        self.assertEqual(service.generate.call_count,1)

    def test_restart_saved_report_and_deleted_artifact_fail_closed(self):
        path=self.report()
        aid=path.rsplit('/',1)[1]
        restarted=create_app(self.catalog).test_client()
        self.assertEqual(restarted.get(path,base_url=BASE).status_code,200)
        (self.catalog.root/self.catalog.record(aid)['relative_path']).unlink()
        self.assertEqual(self.get(path).status_code,400)
        self.assertEqual(self.get(path+'/export?scope=full').status_code,400)

    def test_column_rules_sort_links_exports_and_pagination_share_selection(self):
        path=self.report()
        result=self.service.load(path.rsplit('/',1)[1])
        selected=Selection(filters=(ColumnFilter('ivGauge','ge','0'),ColumnFilter('company','contains','')),
                           sort='ivGauge',direction='asc',columns=('symbol','ivGauge','ota_raw.ivGauge'),page=2)
        query=urlencode(selected.query())
        before=len(self.catalog.runs())
        with patch('trading_scanner.credentials.resolve',side_effect=AssertionError('credentials denied')),patch('trading_scanner.ota_fetch.run_fetch',side_effect=AssertionError('providers denied')):
            response=self.get(path+'?'+query)
            self.assertEqual(response.status_code,200,response.text)
            links=[unescape(link) for link in re.findall('href="([^"]+)"',response.text)]
            filtered=next(link for link in links if 'scope=filtered' in link)
            watchlist=next(link for link in links if '/watchlist?' in link)
            self.assertEqual(self.get(filtered).data,csv_export(result,selected))
            download=self.get(watchlist)
            self.assertEqual(download.data,watchlist_export(result,selected))
            self.assertIn('filtered-watchlist.txt',download.headers['Content-Disposition'])
            self.assertIn('text/plain',download.headers['Content-Type'])
            previous=next(link for link in links if parse_qs(urlsplit(link).query).get('page')==['1'] and '/export' not in link and '/watchlist' not in link)
            migrated=decode_document(parse_qs(urlsplit(previous).query)['expression'][0])
            self.assertEqual([rule['field'] for rule in migrated['root']['rules']],['ivGauge','company'])
            sort=next(link for link in links if parse_qs(urlsplit(link).query).get('sort')==['ivGauge'] and parse_qs(urlsplit(link).query).get('direction')==['desc'])
            self.assertNotIn('page',parse_qs(urlsplit(sort).query))
            self.assertEqual(self.get(sort).status_code,200)
        self.assertEqual(len(self.catalog.runs()),before)

    def test_rule_builder_removal_validation_and_escaping(self):
        path=self.report()
        query=[('field','ivGauge'),('op','eq'),('value','1'),('field',''),('op','contains'),('value','')]
        response=self.get(path+'?'+urlencode(query))
        self.assertEqual(response.status_code,200)
        self.assertIn('Applied filter:',response.text)
        self.assertEqual(response.text.count('name="e.r.0.field"'),1)
        self.assertNotIn('name="e.r.1.field"',response.text)
        for query in ('field=ivGauge&op=gt','field=ivGauge&op=gt&value=nan',
                      'field=unknown&op=eq&value=1','column=unknown',
                      'column=symbol&column=symbol','filters=arbitrary',
                      'sort=score&sort=symbol','search='+('x'*24001)):
            for suffix in ('','/watchlist','/export?scope=filtered&'):
                url=path+suffix+('' if '?' in suffix else '?')+query
                self.assertEqual(self.get(url).status_code,400,url[:100])
        query=urlencode({'field':'company','op':'contains','value':'<script>bad</script>'})
        response=self.get(path+'?'+query)
        self.assertEqual(response.status_code,200)
        self.assertNotIn('<script>bad</script>',response.text)
        self.assertIn('&lt;script&gt;',response.text)
        self.assertEqual(self.get(path+'/watchlist?'+query).data,b'')
