"""Explicit job submission/status and user-started foreground worker."""
import json
import uuid
from .catalog import Catalog
from .core import DataError
from .dashboard import atomic_json
from .ota_config import pairs,MAX_INPUT
from .jobs import Jobs
from .progress import RunProgress,JOB_ERRORS
from .run_ids import new_run_id
from .scan_service import code_revision

COMMANDS=('job-submit-report','job-submit-ota','job-submit-tradier','job-list','job-show','job-cancel','job-recover','job-run')


def add_commands(subs):
    commands={name:subs.add_parser(name,help='USER-RUN: durable job management; job-run executes one job') for name in COMMANDS}
    report=commands['job-submit-report']
    report.add_argument('--prices',required=True);report.add_argument('--ota');report.add_argument('--tradier')
    ota=commands['job-submit-ota'];ota.add_argument('--page-size',type=int,default=600);ota.add_argument('--max-pages',type=int,default=50)
    tradier=commands['job-submit-tradier'];tradier.add_argument('--prices',required=True)
    tradier.add_argument('--profile',choices=('sandbox','production'),required=True);tradier.add_argument('--as-of',required=True)
    for cmd in (ota,tradier):cmd.add_argument('--credential-source',choices=('env','store'),required=True)
    for name,command in commands.items():
        command.add_argument('--demo',action='store_true')
        if name.startswith('job-submit-'):command.add_argument('--action-key')
        elif name!='job-list':command.add_argument('--job',required=True)
    commands['job-recover'].add_argument('--confirm-stopped',action='store_true')


def run_jobs(root,args):
    if args.demo:root=root/'artifacts/web-demo-workspace'
    progress,code=None,None
    try:
        progress=RunProgress(root/'artifacts/logs',new_run_id(),args.command,'unknown',code_revision())
        progress.begin();progress.start('job_run')
        catalog=Catalog(root);catalog.initialize();jobs=Jobs(catalog)
        if args.command in ('job-submit-ota','job-submit-tradier') and args.demo:raise DataError('JOB_INVALID')
        key=getattr(args,'action_key',None) or uuid.uuid4().hex
        if args.command=='job-submit-report':output={'job':jobs.submit_report(key,args.prices,args.ota,args.tradier)}
        elif args.command=='job-submit-ota':
            with (root/'config/ota-screener.json').open('rb') as stream:data=stream.read(MAX_INPUT+1)
            if len(data)>MAX_INPUT:raise DataError('JOB_INVALID')
            output={'job':jobs.submit_ota(key,json.loads(data,object_pairs_hook=pairs),page_size=args.page_size,max_pages=args.max_pages,credential_source=args.credential_source)}
        elif args.command=='job-submit-tradier':output={'job':jobs.submit_tradier(key,args.prices,args.profile,args.as_of,credential_source=args.credential_source)}
        elif args.command=='job-list':output=jobs.list()
        elif args.command=='job-show':output={'job':jobs.get(args.job),'events':jobs.events(args.job)}
        elif args.command=='job-cancel':output={'state':jobs.cancel(args.job)}
        elif args.command=='job-recover':
            jobs.recover(args.job,confirmed_stopped=args.confirm_stopped);output={'state':'interrupted'}
        else:
            progress.pause()
            row=jobs.run(args.job)
            output={'job':row['id'],'state':row['state'],'output_artifact_id':row['output_artifact_id']}
            if row['state'] not in ('succeeded',):code=row['error_code'] or 'JOB_FAILED'
        progress.finish();progress.pause();print(json.dumps(output,indent=2))
    except (Exception,KeyboardInterrupt) as exc:
        code='RUN_CANCELLED' if isinstance(exc,KeyboardInterrupt) else exc.args[0] if isinstance(exc,DataError) and len(exc.args)==1 and exc.args[0] in JOB_ERRORS else 'JOB_FAILED'
        if progress:progress.pause()
        print(f'{code}: job operation stopped; inspect its saved state before any new action.')
    finally:
        if progress:
            try:
                progress.end(code)
                path=root/'artifacts/agent-review'/f'{progress.run_id}.json'
                atomic_json(path,{'schema_version':1,'run_id':progress.run_id,'code_revision':code_revision(),'profile':'unknown',
                                 'checks':[{'name':'durable_job','status':'failed' if code else 'passed'}],'counts':{},'error_code':code})
                print(f'Agent review: {path}')
            except OSError:code='LOG_UNAVAILABLE'
            finally:progress.close()
    return 130 if code=='RUN_CANCELLED' else 1 if code else 0
