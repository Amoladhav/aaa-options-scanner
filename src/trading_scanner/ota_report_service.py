"""Local OTA report application service, shared by CLI and future web jobs."""
from datetime import datetime, timezone
import hashlib
import json
from .run_ids import new_run_id

from .core import DataError, normalize_symbol
from .dashboard import atomic_json
from .ota_config import pairs
from .ota_reporting import ReportOptions, build_report, render_console, render_html, write_rows_csv
from .progress import RunProgress
from .scan_service import code_revision


def demo_snapshot():
    rows = []
    for i in range(24):
        values = {'sector':('Technology','Industrials','ETF')[i%3], 'industry':'Invented example',
                  'last':20+i, 'avgVol30d':1000000+i*12345, 'meanIvPcnt':25+i/2,
                  'totalOpenInterest':10000+i*1000, 'totalOptionsVolume':1000+i*200,
                  'spreadLiquidityPcnt':85+i/10, 'optionable':1, 'customExample':{'synthetic':True}}
        if i==1:
            values['meanIvPcnt']=-1
        if i==2:
            values['meanIvPcnt']=''
        if i==3:
            values['meanIvPcnt']=None
        if i==4:
            values['meanIvPcnt']='35.5'
        rows.append({'symbol':f'DEMO{i:02}','values':values})
    return {'schema_version':2,'source':'ota','profile':'synthetic','representation':'ota_raw',
            'acquisition_status':'completed_short_page','coverage':'synthetic_example',
            'run_id':'0'*32,'retrieved_at':'2026-09-20T12:00:00+00:00','pages_received':1,'rows':rows}


def generate_report(root, *, source=None, options=ReportOptions(), demo=False):
    """Reads one saved snapshot; never fetches, joins, filters or changes inputs."""
    run_id, revision = new_run_id(), code_revision()
    progress, counts, code, destination = None, {}, None, None
    profile = 'synthetic' if demo else 'ota'
    try:
        progress = RunProgress(root / 'artifacts/logs',run_id,'ota-report-demo' if demo else 'ota-report',profile,revision)
        progress.begin()
        progress.start('snapshot_load')
        if demo:
            if source is not None:
                raise DataError('OTA_REPORT_INPUT_INVALID')
            raw = (json.dumps(demo_snapshot(),indent=2)+'\n').encode('utf-8')
        else:
            if source is None:
                candidates = list(root.glob('artifacts/ota/*/results.json'))
                if not candidates:
                    raise DataError('OTA_REPORT_INPUT_MISSING')
                source = max(candidates,key=lambda p:(p.stat().st_mtime_ns,str(p)))
            with source.open('rb') as stream:
                raw = stream.read(220_000_001)
            if len(raw)>220_000_000:
                raise DataError('OTA_REPORT_INPUT_INVALID')
            print(f'Saved input: {source.resolve()}')
        def bad_constant(value):
            raise DataError('OTA_REPORT_INPUT_INVALID')
        snapshot = json.loads(raw,object_pairs_hook=pairs,parse_constant=bad_constant)
        progress.finish()
        progress.start('report_model')
        model = build_report(snapshot,hashlib.sha256(raw).hexdigest(),generated_at=datetime.now(timezone.utc).isoformat(),options=options)
        # An explicit input can also be a saved synthetic demo; retain its label.
        profile = model['profile']
        if profile=='synthetic' and progress.profile!='synthetic':
            progress.set_profile(profile)
        counts = model['summary']
        progress.finish(counts=counts)
        progress.start('reports',total=7)
        parent = root / 'artifacts/ota-reports'
        pending = parent / (run_id+'.pending')
        pending.mkdir(parents=True,exist_ok=False)
        (pending/'source.json').write_bytes(raw)
        progress.advance(1)
        atomic_json(pending/'report.json',model)
        progress.advance(2)
        atomic_json(pending/'field-profile.json',model['field_profile'])
        progress.advance(3)
        write_rows_csv(model,pending/'rows.csv')
        progress.advance(4)
        (pending/'ota-symbols.txt').write_text(''.join(normalize_symbol(row['symbol'])+'\n' for row in model['rows']),encoding='utf-8')
        progress.advance(5)
        (pending/'report.html').write_text(render_html(model),encoding='utf-8')
        progress.advance(6)
        atomic_json(pending/'manifest.json',{'schema_version':1,'status':'completed','run_id':run_id,
                                           'code_revision':revision,'source_sha256':model['source_sha256'],'counts':counts})
        completed = parent / run_id
        pending.rename(completed)
        destination = completed
        progress.finish(counts=counts)
        print(render_console(model))
        print(f'Report: {destination / "report.html"}')
        print(f'All rows CSV: {destination / "rows.csv"}')
        print(f'Report JSON: {destination / "report.json"}')
        print(f'Field profile: {destination / "field-profile.json"}')
    except (Exception,KeyboardInterrupt) as exc:
        code = 'RUN_CANCELLED' if isinstance(exc,KeyboardInterrupt) else 'OTA_REPORT_FAILED'
        if isinstance(exc,DataError) and len(exc.args)==1 and exc.args[0] in ('OTA_REPORT_INPUT_INVALID','OTA_REPORT_INPUT_MISSING'):
            code=exc.args[0]
        elif progress and progress.stage_name in ('snapshot_load','report_model'):
            code='OTA_REPORT_INPUT_INVALID' if code!='RUN_CANCELLED' else code
        if progress:
            progress.pause()
        print(f'{code}: report generation stopped; no fetch or synthetic fallback.')
    finally:
        if progress:
            try:
                progress.end(code,counts=counts)
            except OSError:
                code=code or 'LOG_UNAVAILABLE'
            finally:
                try:
                    progress.close()
                except OSError:
                    code=code or 'LOG_UNAVAILABLE'
    try:
        review=root/'artifacts/agent-review'/f'{run_id}.json'
        atomic_json(review,{'schema_version':1,'run_id':run_id,'code_revision':revision,'profile':profile,
                            'checks':[{'name':'ota_report','status':'failed' if code else 'passed'}],
                            'counts':counts,'error_code':code})
        print(f'Agent review: {review}')
    except OSError:
        code=code or 'OTA_REPORT_FAILED'
        print('OTA_REPORT_FAILED: could not write sanitized review report.')
    return 130 if code=='RUN_CANCELLED' else 1 if code else 0
