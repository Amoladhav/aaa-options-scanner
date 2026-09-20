"""CLI adapter for personal settings and a user-started local schedule worker."""
from datetime import datetime, timezone
import json
import time

from .core import DataError
from .scheduling import ScheduleService, TASKS
from .scheduled_workflows import execute_job


def add_commands(subs):
    parser = subs.add_parser('schedule', help='Personal daily schedule settings; no fetch on configuration')
    actions = parser.add_subparsers(dest='schedule_action', required=True)
    edit = actions.add_parser('set', help='Save personal time/task settings; disabled unless --enable is supplied')
    edit.add_argument('--time', required=True, help='Local HH:MM, for example 05:00')
    edit.add_argument('--timezone', required=True, help='IANA zone, for example America/Los_Angeles')
    edit.add_argument('--task', choices=TASKS, default='ota')
    edit.add_argument('--grace-minutes', type=int, default=60, help='Allow late start within this window (1..180; default 60)')
    edit.add_argument('--enable', action='store_true')
    for action in ('show', 'enable', 'disable'):
        actions.add_parser(action)
    recover = actions.add_parser('acknowledge-stopped', help='USER-RUN: release a crash-blocked job after confirming the worker stopped')
    recover.add_argument('--date', required=True, help='Job local date YYYY-MM-DD')
    recover.add_argument('--confirm-worker-stopped', action='store_true', required=True)
    worker = subs.add_parser('schedule-worker', help='USER-RUN: execute due jobs; keep this process open for daily runs')
    worker.add_argument('--once', action='store_true', help='Check once; suitable for a user-managed OS timer')


def run_schedule(root, args):
    service = ScheduleService(root)
    try:
        if args.command == 'schedule-worker':
            print(f'Schedule state: {service.path}')
            print('Local worker active. Keep the computer awake and this process open. Ctrl+C stops it.')
            previous = None
            while True:
                result = service.tick(datetime.now(timezone.utc), lambda job: execute_job(root, job))
                state = service.view(datetime.now(timezone.utc))
                notice = (state['next_due_local'], state['blocked_by_running_job'], bool(state['settings'] and state['settings']['enabled']))
                if notice != previous or result is not None:
                    print(f"{datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')} INFO schedule-worker | next_due={notice[0]} enabled={notice[2]} blocked={notice[1]} last_status={result['status'] if result else 'idle'}", flush=True)
                    previous = notice
                if result and result['status'] == 'cancelled':
                    return 130
                if args.once:
                    return 1 if result and result['status'] != 'succeeded' else 0
                time.sleep(30)
        elif args.schedule_action == 'set':
            service.configure({'schema_version':1, 'time':args.time, 'timezone':args.timezone, 'task':args.task,
                               'grace_minutes':args.grace_minutes, 'enabled':args.enable})
        elif args.schedule_action in ('enable', 'disable'):
            service.set_enabled(args.schedule_action == 'enable')
        elif args.schedule_action == 'acknowledge-stopped':
            service.acknowledge_stopped(args.date)
        print(f'Personal schedule: {service.path}')
        print(json.dumps(service.view(datetime.now(timezone.utc)), indent=2))
        return 0
    except KeyboardInterrupt:
        print('RUN_CANCELLED: schedule worker stopped. No automatic replay of this attempt.')
        return 130
    except Exception as exc:
        allowed = {'SCHEDULE_INVALID', 'SCHEDULE_TIMEZONE_UNAVAILABLE', 'SCHEDULE_NOT_CONFIGURED', 'SCHEDULE_BUSY', 'SCHEDULE_STATE_INVALID'}
        code = exc.args[0] if isinstance(exc, DataError) and len(exc.args)==1 and exc.args[0] in allowed else 'SCHEDULE_FAILED'
        print(f'{code}: schedule stopped; inspect schedule status and printed provider review reports. No automatic replay.')
        return 1
