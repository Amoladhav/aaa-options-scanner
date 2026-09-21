"""Shared, user-run credential lifecycle; no access on import or guidance reads."""
from .core import DataError
from .credentials import VARIABLES, resolve, hidden_prompt

ERRORS = {'CREDENTIAL_EXISTS', 'CREDENTIAL_NOT_FOUND', 'CREDENTIAL_ACTION_INVALID'}


def guidance(provider, profile):
    variable = VARIABLES.get((provider, profile))
    if variable is None:
        raise DataError('CREDENTIAL_PROFILE_INVALID')
    return {'provider':provider, 'profile':profile, 'variable':variable,
            'storage':'OS store or explicit environment injection',
            'renewal':'Renew the OTA session manually after expiry.' if provider=='ota' else
                      'Replace locally after provider-side rotation; local removal does not revoke the key.',
            'authentication':'Local format/status checks do not verify provider access.'}


def manage(provider, profile, action, *, store=None, prompt=None):
    """One explicit profile; never return credential values or their properties.

    Native stores have no cross-process compare-and-swap API. Do not run
    concurrent credential editors. Add/replace preconditions prevent accidental
    overwrites in the ordinary single-user flow, not a distributed transaction.
    """
    guidance(provider,profile)
    if action not in ('status','add','replace','remove'):
        raise DataError('CREDENTIAL_ACTION_INVALID')
    if store is None:
        from .token_store import operate
        store = operate
    kwargs = {'provider':provider,'profile':None if provider=='ota' else profile}
    try:
        existing = store('get',**kwargs)
        present = existing is not None
        if action=='status':
            if present:
                resolve(provider,profile,source='store',store=lambda **_:existing)
            return {'present':present,'format_valid':present,'authentication_checked':False}
        existing = None
        if action=='add' and present:
            raise DataError('CREDENTIAL_EXISTS')
        if action=='replace' and not present:
            raise DataError('CREDENTIAL_NOT_FOUND')
        if action=='remove':
            if present:
                store('delete',**kwargs)
            return {'removed':present,'authentication_checked':False}
        value = resolve(provider,profile,source='prompt',allow_prompt=True,
                        prompt=prompt or (lambda:hidden_prompt('Credential (hidden; saved to selected OS store): ')))
        try:
            store('set',value,**kwargs)
        finally:
            value = None
        return {'saved':True,'authentication_checked':False}
    except DataError as exc:
        from .credentials import ERRORS as RESOLUTION_ERRORS
        if len(exc.args)==1 and exc.args[0] in ERRORS | RESOLUTION_ERRORS | {'TOKEN_STORE_EMPTY','TOKEN_STORE_UNAVAILABLE'}:
            raise
        raise DataError('CREDENTIAL_UNAVAILABLE') from None
    except Exception:
        raise DataError('CREDENTIAL_UNAVAILABLE') from None


def add_commands(subs):
    command = subs.add_parser('credential-manage',help='USER-RUN: manage one OS-stored credential; no provider call')
    command.add_argument('action',choices=('guide','status','add','replace','remove'))
    command.add_argument('--provider',choices=('ota','tradier'),required=True)
    command.add_argument('--profile',choices=('ota','sandbox','production'),required=True)


def run_setup(root,args):
    import json
    from .credentials import ERRORS as RESOLUTION_ERRORS
    from .dashboard import atomic_json
    from .progress import RunProgress
    from .run_ids import new_run_id
    from .scan_service import code_revision
    progress, code = None, None
    try:
        progress = RunProgress(root/'artifacts/logs',new_run_id(),'credential-manage',args.profile,code_revision())
        progress.begin();progress.start('token_store')
        result = guidance(args.provider,args.profile) if args.action=='guide' else manage(args.provider,args.profile,args.action)
        progress.finish();progress.pause()
        print(json.dumps(result,indent=2))
        print('Provider authentication not checked. Local removal does not revoke a provider credential.')
    except (Exception,KeyboardInterrupt) as exc:
        safe = ERRORS | RESOLUTION_ERRORS | {'TOKEN_STORE_EMPTY','TOKEN_STORE_UNAVAILABLE'}
        code = ('RUN_CANCELLED' if isinstance(exc,KeyboardInterrupt) else
                exc.args[0] if isinstance(exc,DataError) and len(exc.args)==1 and exc.args[0] in safe else 'CREDENTIAL_UNAVAILABLE')
        if progress: progress.pause()
        print(code)
    finally:
        if progress:
            try:
                progress.end(code)
                path=root/'artifacts/agent-review'/f'{progress.run_id}.json'
                atomic_json(path,{'schema_version':1,'run_id':progress.run_id,'code_revision':code_revision(),
                                 'profile':args.profile,'checks':[{'name':'credential_lifecycle','status':'failed' if code else 'passed'}],
                                 'counts':{},'error_code':code})
                print(f'Agent review: {path}')
            except OSError:
                code='LOG_UNAVAILABLE'
            finally:
                progress.close()
    return 130 if code=='RUN_CANCELLED' else 1 if code else 0
