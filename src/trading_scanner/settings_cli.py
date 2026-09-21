"""CLI adapter for private screeners and display preferences."""
import json
from pathlib import Path
from .catalog import Catalog
from .core import DataError
from .dashboard import atomic_json
from .ota_config import pairs
from .progress import RunProgress
from .run_ids import new_run_id
from .scan_service import code_revision
from .workspace_settings import WorkspaceSettings,MAX_PAYLOAD,selection_payload
from .report_selection import Selection

COMMANDS=('screener-list','screener-show','screener-save','preferences-show','preferences-set','screener-export')


def add_commands(subs):
    commands={name:subs.add_parser(name,help='USER-RUN: saved screeners or display preferences') for name in COMMANDS}
    commands['screener-show'].add_argument('--revision',required=True)
    export=commands['screener-export']
    export.add_argument('--revision',required=True);export.add_argument('--report',required=True)
    export.add_argument('--destination',type=Path,required=True)
    export.add_argument('--format',choices=('csv','watchlist'),default='csv')
    save=commands['screener-save']
    save.add_argument('--report',required=True);save.add_argument('--name',required=True)
    save.add_argument('--selection-file',type=Path)
    save.add_argument('--expected')
    prefs=commands['preferences-set']
    prefs.add_argument('--page-size',type=int,choices=(25,50,100,250),required=True)
    prefs.add_argument('--display-timezone',choices=('local','utc'),required=True)
    prefs.add_argument('--expected')
    for command in commands.values():command.add_argument('--demo',action='store_true')


def run_settings(root,args):
    if args.demo:root=root/'artifacts/web-demo-workspace'
    progress,code=None,None
    try:
        progress=RunProgress(root/'artifacts/logs',new_run_id(),args.command,'unknown',code_revision())
        progress.begin();progress.start('workspace_settings')
        catalog=Catalog(root);catalog.initialize();service=WorkspaceSettings(catalog)
        if args.command=='screener-list': output=service.list()
        elif args.command=='screener-show':
            row=service.get(args.revision);output={'revision':row,'history':service.history(row['kind'],row['name'])}
        elif args.command=='screener-export':
            from .report_service import ReportService,csv_export
            from .report_selection import watchlist_export
            result=ReportService(catalog).load(args.report)
            selection=service.apply(args.revision,result)
            data=csv_export(result,selection) if args.format=='csv' else watchlist_export(result,selection)
            with args.destination.open('xb') as stream:stream.write(data)
            output={'output':str(args.destination)}
        elif args.command=='screener-save':
            value=selection_payload(Selection())
            if args.selection_file:
                with args.selection_file.open('rb') as stream:data=stream.read(MAX_PAYLOAD+1)
                if len(data)>MAX_PAYLOAD:raise DataError('SETTINGS_INVALID')
                value=json.loads(data,object_pairs_hook=pairs)
            output={'revision':service.save('screener',args.name,value,expected=args.expected,source=args.report)}
        elif args.command=='preferences-show':
            revision,value=service.preference_state();output={'revision':revision,'preferences':value}
        else:
            output={'revision':service.save('preferences','workspace',{'page_size':args.page_size,'display_timezone':args.display_timezone},expected=args.expected)}
        progress.finish();progress.pause();print(json.dumps(output,indent=2))
    except (Exception,KeyboardInterrupt) as exc:
        safe={'SETTINGS_INVALID','SETTINGS_NOT_FOUND','SETTINGS_CONFLICT','REPORT_COLUMN_UNKNOWN',
              'REPORT_SELECTION_INVALID','REPORT_EXPRESSION_INVALID','REPORT_EXPRESSION_UNITS'}
        code='RUN_CANCELLED' if isinstance(exc,KeyboardInterrupt) else exc.args[0] if isinstance(exc,DataError) and len(exc.args)==1 and exc.args[0] in safe else 'SETTINGS_INVALID'
        if progress:progress.pause()
        print(f'{code}: reload the current revision and check the selected fields.')
    finally:
        if progress:
            try:
                progress.end(code)
                path=root/'artifacts/agent-review'/f'{progress.run_id}.json'
                atomic_json(path,{'schema_version':1,'run_id':progress.run_id,'code_revision':code_revision(),
                                 'profile':'unknown','checks':[{'name':'workspace_settings','status':'failed' if code else 'passed'}],
                                 'counts':{},'error_code':code})
                print(f'Agent review: {path}')
            except OSError:code='LOG_UNAVAILABLE'
            finally:progress.close()
    return 130 if code=='RUN_CANCELLED' else 1 if code else 0
