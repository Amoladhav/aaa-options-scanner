"""Same-origin localhost adapter. No provider/credential/scheduling routes."""
from datetime import datetime, timezone
from dataclasses import replace
import hmac
import json
import secrets
import threading
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, Response, abort, redirect, render_template, request, session, url_for, g
from werkzeug.exceptions import HTTPException

from ..core import DataError
from ..report_service import ReportService, Selection, select_rows, csv_export, coverage
from ..report_selection import (ColumnFilter, report_columns, watchlist_export,
                                DEFAULT_COLUMNS, OPERATORS, MAX_RULES, cell_text)
from ..report_expressions import (expression_for_selection, expression_summary, decode_document,
    edit_expression, compile_expression, ERROR_MESSAGES, UNITS, MAX_DEPTH)


def validate_port(port):
    if type(port) is not int or not 1024<=port<=65535:
        raise DataError('WEB_PORT_INVALID')
    return port


def create_app(catalog, *, port=8765, service=None):
    validate_port(port)
    app=Flask(__name__,static_folder=None,template_folder='templates')
    app.config.update(SECRET_KEY=secrets.token_hex(32),DEBUG=False,TESTING=False,
                      TRUSTED_HOSTS=['127.0.0.1'],MAX_CONTENT_LENGTH=262144,
                      MAX_FORM_MEMORY_SIZE=262144,MAX_FORM_PARTS=12,
                      SESSION_COOKIE_NAME='scanner_local_session',SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Strict',SESSION_COOKIE_PATH='/')
    origin=f'http://127.0.0.1:{port}'
    service=service or ReportService(catalog)
    mutation_lock=threading.Lock()
    from ..workspace_settings import WorkspaceSettings,selection_payload
    workspace_settings=WorkspaceSettings(catalog)
    app.add_template_filter(cell_text, 'cell_text')

    @app.template_filter('local_time')
    def local_time(value):
        if not isinstance(value,str):
            return value
        try:
            stamp=datetime.fromisoformat(value)
            zone=timezone.utc if g.preferences['display_timezone']=='utc' else None
            return stamp.astimezone(zone).isoformat(timespec='seconds') if stamp.tzinfo else value
        except ValueError:
            return value

    @app.before_request
    def boundary():
        if (request.host!=f'127.0.0.1:{port}' or request.remote_addr!='127.0.0.1'
                or request.scheme!='http'
                or any(key.lower()=='forwarded' or key.lower().startswith('x-forwarded-') for key in request.headers.keys())
                or request.headers.get('Origin') not in (None,origin)
                or request.headers.get('Sec-Fetch-Site')=='cross-site'):
            abort(403)
        if request.method not in ('GET','HEAD','POST'):
            abort(405)
        if request.method=='POST':
            if request.headers.get('Origin')!=origin or request.mimetype!='application/x-www-form-urlencoded':
                abort(403)
            expected=session.get('csrf')
            supplied=request.form.get('csrf','')
            if not isinstance(expected,str) or not hmac.compare_digest(expected,supplied):
                abort(403)
        if request.endpoint not in ('health','static') and 'csrf' not in session:
            session['csrf']=secrets.token_hex(32)
        g.preference_revision,g.preferences=workspace_settings.preference_state()

    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
                                 'X-Frame-Options':'DENY','Referrer-Policy':'no-referrer',
                                 'Content-Security-Policy':"default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"})
        return response

    @app.errorhandler(Exception)
    def safe_error(exc):
        status=409 if isinstance(exc,DataError) and exc.args==('SETTINGS_CONFLICT',) else exc.code if isinstance(exc,HTTPException) else 400 if isinstance(exc,(DataError,ValueError,KeyError,TypeError)) else 500
        # Do not echo paths, headers, source values or arbitrary exceptions.
        return render_template('error.html',status=status),status

    @app.get('/assets/app.css')
    def style():
        return Response(Path(__file__).with_name('static').joinpath('app.css').read_bytes(),mimetype='text/css')

    @app.get('/health')
    def health():
        return {'status':'ok','schema_version':1,'providers_enabled':False,'scheduling_enabled':False}

    @app.get('/')
    def sources():
        return render_template('sources.html',artifacts=catalog.list_artifacts())

    @app.post('/reports')
    def generate():
        if set(request.form)-{'csrf','prices','ota','tradier'} or any(len(request.form.getlist(key))!=1 for key in request.form):
            abort(400)
        if not mutation_lock.acquire(blocking=False):
            abort(409)
        try:
            aid=service.generate(request.form.get('prices',''),request.form.get('ota') or None,request.form.get('tradier') or None)
        finally:
            mutation_lock.release()
        return redirect(url_for('report',artifact_id=aid),code=303)

    def selection():
        editor_keys={key for key in request.args if key.startswith('e.') or key in ('draft','action')}
        if editor_keys and request.endpoint!='report':
            raise DataError('REPORT_SELECTION_INVALID')
        if set(request.args)-editor_keys-{'search','group','tail','percent','sort','direction','page','page_size',
                              'field','op','value','column','scope','expression'}:
            raise DataError('REPORT_SELECTION_INVALID')
        if len(request.query_string)>131072 or any(len(request.args.getlist(key))!=1 for key in request.args if key not in ('field','op','value','column')):
            raise DataError('REPORT_SELECTION_INVALID')
        values={'page_size':g.preferences['page_size'],**request.args.to_dict()}
        values.pop('scope',None)
        for key in editor_keys:
            values.pop(key,None)
        fields,ops,terms=(request.args.getlist(key) for key in ('field','op','value'))
        if not len(fields)==len(ops)==len(terms) or len(fields)>MAX_RULES+1:
            raise DataError('REPORT_FILTER_INVALID')
        for key in ('field','op','value','column'):
            values.pop(key,None)
        # An empty column removes a rule. The final empty row adds the next one.
        rules=tuple(ColumnFilter(field,op,term) for field,op,term in zip(fields,ops,terms) if field)
        values.update(filters=rules,columns=tuple(request.args.getlist('column')))
        return Selection.from_mapping(values)

    @app.get('/reports/<artifact_id>')
    def report(artifact_id):
        result=service.load(artifact_id)
        if 'screener' in request.args:
            if set(request.args)!={'screener'} or len(request.args.getlist('screener'))!=1:abort(400)
            selected=workspace_settings.apply(request.args['screener'],result)
        else:
            selected=selection()
        columns=report_columns(result)
        active=expression_for_selection(selected)
        if selected.filters:
            selected=replace(selected,filters=(),expression=active)
        draft=request.args.get('draft',active)
        action=request.args.get('action')
        edits={key:request.args[key] for key in request.args if key.startswith('e.')}
        if (edits or 'draft' in request.args) and not action or action and 'draft' not in request.args:
            raise DataError('REPORT_EXPRESSION_INVALID')
        decode_document(draft)
        editor_error=None
        if action:
            try:
                draft=edit_expression(draft,edits,action)
                if action in ('apply','clear'):
                    compile_expression(draft,set(columns))
                    selected=replace(selected,filters=(),expression=draft,page=1)
                    active=draft
            except DataError as exc:
                editor_error=ERROR_MESSAGES.get(str(exc),ERROR_MESSAGES['REPORT_EXPRESSION_INVALID'])
        rows=select_rows(result,selected)
        start=(selected.page-1)*selected.page_size
        params=selected.query()
        links={}
        for key,page in (('previous',selected.page-1),('next',selected.page+1)):
            links[key]=url_for('report',artifact_id=artifact_id)+'?'+urlencode([(k,v) for k,v in params if k!='page']+[('page',page)])
        links['full']=url_for('export',artifact_id=artifact_id)+'?scope=full'
        links['filtered']=url_for('export',artifact_id=artifact_id)+'?'+urlencode(params+[('scope','filtered')])
        links['watchlist']=url_for('watchlist',artifact_id=artifact_id)+'?'+urlencode(params)
        displayed=selected.columns or DEFAULT_COLUMNS
        sort_links={col:url_for('report',artifact_id=artifact_id)+'?'+urlencode(
            [(k,v) for k,v in params if k not in ('sort','direction','page')]+
            [('sort',col),('direction','asc' if selected.sort==col and selected.direction=='desc' else 'desc')]) for col in displayed}
        return render_template('report.html',artifact_id=artifact_id,result=result,rows=rows[start:start+selected.page_size],
                               selection=selected,total=len(rows),start=start,links=links,counts=coverage(result),
                               columns=columns,displayed=displayed,operators=OPERATORS,sort_links=sort_links,
                               draft=draft,editor_tree=decode_document(draft)['root'],editor_error=editor_error,
                               editor_params=params,
                               active_summary=expression_summary(active),draft_pending=draft!=active,
                               screeners=workspace_settings.list(),saved_payload=json.dumps(selection_payload(selected)),
                               units=UNITS,max_depth=MAX_DEPTH),400 if editor_error else 200

    @app.get('/reports/<artifact_id>/export')
    def export(artifact_id):
        scope=request.args.get('scope')
        if scope not in ('full','filtered') or len(request.args.getlist('scope'))!=1:
            abort(400)
        selected=selection()
        result=service.load(artifact_id)
        data=csv_export(result,selected if scope=='filtered' else None)
        return Response(data,mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename="master-{scope}.csv"'})

    @app.get('/reports/<artifact_id>/watchlist')
    def watchlist(artifact_id):
        selected=selection()
        data=watchlist_export(service.load(artifact_id),selected)
        return Response(data,mimetype='text/plain',headers={'Content-Disposition':'attachment; filename="filtered-watchlist.txt"'})

    @app.get('/settings')
    def settings():
        from ..credential_setup import guidance
        return render_template('settings.html',preferences=g.preferences,preference_revision=g.preference_revision,providers=[guidance('ota','ota'),
                               guidance('tradier','sandbox'),guidance('tradier','production')])

    def strict_form(keys):
        if set(request.form)!=set(keys) or any(len(request.form.getlist(key))!=1 for key in request.form):abort(400)

    @app.post('/preferences')
    def save_preferences():
        strict_form(('csrf','expected','page_size','display_timezone'))
        workspace_settings.save('preferences','workspace',{'page_size':int(request.form['page_size']),
                                'display_timezone':request.form['display_timezone']},expected=request.form['expected'] or None)
        return redirect(url_for('settings'),code=303)

    @app.get('/screeners')
    def screeners():
        return render_template('screeners.html',screeners=workspace_settings.list(),revision=None)

    @app.get('/screeners/<revision_id>')
    def screener_revision(revision_id):
        row=workspace_settings.get(revision_id)
        if row['kind']!='screener':abort(400)
        return render_template('screeners.html',screeners=workspace_settings.list(),revision=row,
                               history=workspace_settings.history('screener',row['name']))

    @app.post('/screeners')
    def save_screener():
        strict_form(('csrf','expected','name','report','selection'))
        expected=request.form['expected'] or None
        name=request.form['name']
        if expected and not name:
            previous=workspace_settings.get(expected)
            if previous['kind']!='screener':abort(400)
            name=previous['name']
        from ..ota_config import pairs
        payload=json.loads(request.form['selection'],object_pairs_hook=pairs)
        revision=workspace_settings.save('screener',name,payload,expected=expected,source=request.form['report'])
        return redirect(url_for('screener_revision',revision_id=revision),code=303)

    @app.get('/runs')
    def runs():
        return render_template('runs.html',runs=catalog.runs(),artifacts=catalog.list_artifacts())

    return app
