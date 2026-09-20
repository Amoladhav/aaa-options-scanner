"""Explicit user-run indexing of saved sources; no implicit discovery or fetch."""
import json
from pathlib import Path

from .catalog import Catalog, MAX_BYTES, confined
from .core import DataError, calculate
from .dashboard import ota_checked, attach_tradier
from .ota_config import pairs


def validate_source(payload, kind):
    if not isinstance(payload, dict):
        raise DataError('CATALOG_INPUT_INVALID')
    if kind == 'prices':
        if payload.get('profile') != 'public':
            raise DataError('CATALOG_INPUT_INVALID')
        calculate(payload)
        return 'public', payload['universe'], payload.get('membership_observed_at')
    if kind == 'ota':
        ota_checked(payload, 'public')
        return 'ota', None, payload.get('retrieved_at')
    if kind == 'tradier':
        if (payload.get('representation') != 'tradier_batch'
                or payload.get('status') not in ('completed','completed_with_errors')
                or not isinstance(payload.get('rows'),list) or not 1 <= len(payload['rows']) <= 2000):
            raise DataError('CATALOG_INPUT_INVALID')
        # Structural/profile validation here; membership compatibility is checked
        # again against the selected price master at report composition time.
        attach_tradier({'profile':'public','master_id':payload.get('master_id'),
                        'combined':[{'symbol':r['symbol']} for r in payload['rows']]}, [payload])
        return payload['profile'], None, payload.get('started_at')
    raise DataError('CATALOG_KIND_INVALID')


def index_source(catalog, path, kind):
    path = Path(path)
    path = path if path.is_absolute() else catalog.root / path
    try:
        relative = path.relative_to(catalog.root).as_posix()
    except ValueError:
        raise DataError('CATALOG_PATH_INVALID') from None
    path = confined(catalog.root, relative)
    parts = relative.split('/')
    permitted = (kind == 'prices' and len(parts)==5 and parts[:3]==['artifacts','runs','public'] and parts[-1]=='snapshot.json'
                 or kind == 'ota' and len(parts)==4 and parts[:2]==['artifacts','ota'] and parts[-1]=='results.json'
                 or kind == 'tradier' and len(parts)==5 and parts[:2]==['artifacts','tradier'] and parts[2] in ('sandbox','production') and parts[-1]=='batch.json')
    if not permitted:
        raise DataError('CATALOG_PATH_INVALID')
    with path.open('rb') as stream:
        data = stream.read(MAX_BYTES+1)
    if len(data)>MAX_BYTES:
        raise DataError('CATALOG_INPUT_INVALID')
    payload = json.loads(data,object_pairs_hook=pairs)
    profile, master, stamp = validate_source(payload,kind)
    if kind=='tradier' and parts[2]!=profile:
        raise DataError('CATALOG_INPUT_INVALID')
    return catalog.publish(data,kind=kind,profile=profile,master=master,observed_at=stamp,
                           state='partial' if payload.get('status')=='completed_with_errors' else 'succeeded')


def run_catalog(root,args):
    from .progress import RunProgress
    from .run_ids import new_run_id
    from .scan_service import code_revision
    from .dashboard import atomic_json
    progress, code, counts = None, None, {}
    try:
        progress = RunProgress(root/'artifacts/logs',new_run_id(),args.command,'unknown',code_revision())
        progress.begin(); progress.start('catalog')
        catalog = Catalog(root)
        catalog.initialize()
        if args.command=='catalog-index':
            aid = index_source(catalog,args.input,args.kind)
            print(f'Artifact ID: {aid}')
            counts={'indexed':1}
        elif args.command=='catalog-reconcile':
            counts=catalog.reconcile()
            if counts['missing'] or counts['changed'] or counts['orphans'] or counts['pending']:
                code='CATALOG_RECONCILIATION_REQUIRED'
        progress.finish(counts=counts)
    except Exception:
        code='CATALOG_FAILED'
        print('CATALOG_FAILED: check source kind, workspace path, format and local storage.')
    finally:
        if progress:
            try:
                progress.end(code,counts=counts)
                path=root/'artifacts/agent-review'/f'{progress.run_id}.json'
                atomic_json(path,{'schema_version':1,'run_id':progress.run_id,'code_revision':code_revision(),
                                 'profile':'unknown','checks':[{'name':'catalog','status':'failed' if code else 'passed'}],
                                 'counts':counts,'error_code':code})
                print(f'Agent review: {path}')
            except OSError:
                code='LOG_UNAVAILABLE'
            finally:
                progress.close()
    return 1 if code else 0
