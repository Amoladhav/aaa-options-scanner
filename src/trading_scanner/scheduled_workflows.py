"""User-run scheduled workflow dispatch shared by worker and future web jobs."""
from argparse import Namespace
from .core import DataError
from .scheduling import TASKS

def execute_job(root, job):
    """Shared application dispatch, never a shell command or CLI invocation."""
    from .ota_fetch import run_fetch, DEFAULT_PAGE_SIZE, DEFAULT_MAX_PAGES
    from .workflow import run_daily
    from .progress import RunProgress
    from .scan_service import code_revision
    from .dashboard import atomic_json
    if job['settings']['task'] not in TASKS:
        raise DataError('SCHEDULE_INVALID')
    revision = code_revision()
    progress = RunProgress(root / 'artifacts/logs', job['id'], 'schedule-run', 'ota' if job['settings']['task']=='ota' else 'public', revision)
    code = 'SCHEDULE_TASK_FAILED'
    try:
        progress.begin()
        progress.start('scheduled_job')
        if job['settings']['task'] == 'ota':
            result = run_fetch(root, use_stored_token=True)
        else:
            result = run_daily(root, Namespace(page_size=DEFAULT_PAGE_SIZE, max_pages=DEFAULT_MAX_PAGES, use_stored_token=True, filters=None))
        code = None if result == 0 else 'RUN_CANCELLED' if result == 130 else 'SCHEDULE_TASK_FAILED'
        return result
    except KeyboardInterrupt:
        code = 'RUN_CANCELLED'
        raise
    finally:
        try:
            progress.end(code)
            review = root / 'artifacts/agent-review' / f"{job['id']}.json"
            atomic_json(review, {'schema_version': 1, 'run_id': job['id'], 'code_revision': revision,
                                'profile': 'ota' if job['settings']['task']=='ota' else 'public',
                                'checks': [{'name':'scheduled_job', 'status':'failed' if code else 'passed'}],
                                'counts': {}, 'error_code': code})
            print(f'Agent review: {review}')
        finally:
            progress.close()
