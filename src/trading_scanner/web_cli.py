"""Explicit localhost startup. Saved data only; no provider worker activation."""
import logging
from .core import DataError


def run_web(root,args):
    from .catalog import Catalog
    from .report_service import ReportService
    from .progress import RunProgress
    from .run_ids import new_run_id
    from .scan_service import code_revision
    from .dashboard import atomic_json
    progress,server,code=None,None,None
    workspace=root/'artifacts/web-demo-workspace' if args.demo else root
    try:
        from .web import create_app,validate_port
        from waitress import create_server
        validate_port(args.port)
        progress=RunProgress(workspace/'artifacts/logs',new_run_id(),'web','synthetic' if args.demo else 'public',code_revision())
        progress.begin();progress.start('web_start')
        catalog=Catalog(workspace);catalog.initialize()
        service=ReportService(catalog)
        if args.demo:
            prices,ota=service.demo_sources()
            if not catalog.list_artifacts('report'):
                service.generate(prices,ota)
        app=create_app(catalog,port=args.port,service=service)
        # WSGI exceptions are handled with fixed responses. Do not let server
        # diagnostics emit request data or arbitrary application exception text.
        for name in ('waitress','waitress.queue'):
            logger=logging.getLogger(name)
            logger.handlers=[logging.NullHandler()];logger.propagate=False
        server=create_server(app,host='127.0.0.1',port=args.port,threads=4,
                             expose_tracebacks=False,log_socket_errors=False,
                             max_request_body_size=4096,max_request_header_size=16384,
                             channel_timeout=30,clear_untrusted_proxy_headers=False)
        progress.finish();progress.pause()
        print(f'Local preview: http://127.0.0.1:{args.port}',flush=True)
        print('Saved data only. Provider controls unavailable; scheduling disabled in this app. Stop with Ctrl+C.',flush=True)
        server.run()
    except KeyboardInterrupt:
        code='RUN_CANCELLED'
    except ImportError:
        code='DEPENDENCY_UNAVAILABLE'
        print('DEPENDENCY_UNAVAILABLE: install the reviewed requirements-web.txt into your selected interpreter.')
    except Exception:
        code='WEB_FAILED'
        print('WEB_FAILED: check the port, optional dependencies and writable local workspace; no provider action ran.')
    finally:
        if server:
            server.close()
        if progress:
            try:
                progress.end(code);progress.close()
                path=workspace/'artifacts/agent-review'/f'{progress.run_id}.json'
                atomic_json(path,{'schema_version':1,'run_id':progress.run_id,'code_revision':code_revision(),
                                 'profile':'synthetic' if args.demo else 'public',
                                 'checks':[{'name':'local_web','status':'cancelled' if code=='RUN_CANCELLED' else 'failed' if code else 'passed'}],
                                 'counts':{},'error_code':code})
                print(f'Agent review: {path}')
            except OSError:
                code='LOG_UNAVAILABLE'
    return 130 if code=='RUN_CANCELLED' else 1 if code else 0
