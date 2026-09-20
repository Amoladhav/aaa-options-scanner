"""Same-origin localhost adapter. No provider/credential/scheduling routes."""
from dataclasses import asdict
from datetime import datetime
import hmac
import secrets
import threading
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, Response, abort, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException

from ..core import DataError
from ..report_service import ReportService, Selection, select_rows, csv_export, coverage


def validate_port(port):
    if type(port) is not int or not 1024<=port<=65535:
        raise DataError('WEB_PORT_INVALID')
    return port


def create_app(catalog, *, port=8765, service=None):
    validate_port(port)
    app=Flask(__name__,static_folder=None,template_folder='templates')
    app.config.update(SECRET_KEY=secrets.token_hex(32),DEBUG=False,TESTING=False,
                      TRUSTED_HOSTS=['127.0.0.1'],MAX_CONTENT_LENGTH=4096,
                      MAX_FORM_MEMORY_SIZE=4096,MAX_FORM_PARTS=12,
                      SESSION_COOKIE_NAME='scanner_local_session',SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Strict',SESSION_COOKIE_PATH='/')
    origin=f'http://127.0.0.1:{port}'
    service=service or ReportService(catalog)
    mutation_lock=threading.Lock()

    @app.template_filter('local_time')
    def local_time(value):
        if not isinstance(value,str):
            return value
        try:
            stamp=datetime.fromisoformat(value)
            return stamp.astimezone().isoformat(timespec='seconds') if stamp.tzinfo else value
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

    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
                                 'X-Frame-Options':'DENY','Referrer-Policy':'no-referrer',
                                 'Content-Security-Policy':"default-src 'none'; style-src 'self'; img-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"})
        return response

    @app.errorhandler(Exception)
    def safe_error(exc):
        status=exc.code if isinstance(exc,HTTPException) else 400 if isinstance(exc,(DataError,ValueError,KeyError,TypeError)) else 500
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
        if any(len(request.args.getlist(key))!=1 for key in request.args):
            raise DataError('REPORT_SELECTION_INVALID')
        values=request.args.to_dict()
        values.pop('scope',None)
        return Selection.from_mapping(values)

    @app.get('/reports/<artifact_id>')
    def report(artifact_id):
        result=service.load(artifact_id)
        selected=selection();rows=select_rows(result,selected)
        start=(selected.page-1)*selected.page_size
        params=asdict(selected)
        links={}
        for key,page in (('previous',selected.page-1),('next',selected.page+1)):
            links[key]=url_for('report',artifact_id=artifact_id)+'?'+urlencode({**params,'page':page})
        links['full']=url_for('export',artifact_id=artifact_id)+'?scope=full'
        links['filtered']=url_for('export',artifact_id=artifact_id)+'?'+urlencode({**params,'scope':'filtered'})
        return render_template('report.html',artifact_id=artifact_id,result=result,rows=rows[start:start+selected.page_size],
                               selection=selected,total=len(rows),start=start,links=links,counts=coverage(result))

    @app.get('/reports/<artifact_id>/export')
    def export(artifact_id):
        scope=request.args.get('scope')
        if scope not in ('full','filtered') or len(request.args.getlist('scope'))!=1:
            abort(400)
        selected=selection()
        result=service.load(artifact_id)
        data=csv_export(result,selected if scope=='filtered' else None)
        return Response(data,mimetype='text/csv',headers={'Content-Disposition':f'attachment; filename="master-{scope}.csv"'})

    @app.get('/runs')
    def runs():
        return render_template('runs.html',runs=catalog.runs(),artifacts=catalog.list_artifacts())

    return app
