# Personal daily scheduling

Scheduling is a personal workspace preference. The CLI and future web interface
use the same `ScheduleService` settings, validation, next-occurrence calculation,
transactional claims and history. No web server or OS task is installed by these
commands. Schedule settings/history live in ignored
`artifacts/scheduler/schedule.sqlite3`, not committed configuration or credentials.

## Configure your time and task

From the project root on Ubuntu/WSL/macOS:

```bash
.venv/bin/python -I run.py schedule set --time 05:00 --timezone America/Los_Angeles --task ota --enable
.venv/bin/python -I run.py schedule show
```

Native Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -I run.py schedule set --time 05:00 --timezone America/Los_Angeles --task ota --enable
.\.venv\Scripts\python.exe -I run.py schedule show
```

05:00 means 5 AM Pacific local time: PST in winter and PDT in summer. The named
timezone preserves that clock time through DST; it is not a fixed UTC-08:00 offset.
The example is editable, not a global application default. `--timezone` is required
so an abbreviation or machine offset cannot silently select the wrong zone.

Settings are versioned and include time, timezone, task, enabled state and a late
start window (`--grace-minutes`, default 60, allowed 1–180). `schedule set` replaces
those settings and disables scheduling unless `--enable` is supplied. `show`
displays current settings, next due time, blocked status and the last 30 jobs.
Supported tasks:

- `ota`: fetch the current locally saved OTA screener, with normal profiling/output.
- `daily`: public prices → OTA → combined dashboard, using newly produced inputs.
  It does not fetch Tradier; Tradier scheduling remains a future task registration.

These tasks read the latest local config at execution. OTA captures preserve the
criteria actually sent; the schedule job preserves its own settings snapshot.
One schedule runs every calendar day, including weekends/holidays. Market-calendar
schedules, multiple schedules and arbitrary shell commands are not implemented.

If timezone data is missing, `SCHEDULE_TIMEZONE_UNAVAILABLE` stops configuration.
Python uses an OS IANA database or the first-party `tzdata` fallback, which is often
needed on Windows ([Python documentation](https://docs.python.org/3/library/zoneinfo.html)).
After reviewing `requirements-scheduling.txt`, install the pinned fallback locally:

```bash
.venv/bin/python -m pip install --only-binary=:all: -r requirements-scheduling.txt
```

```powershell
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-scheduling.txt
```

## Credentials and worker startup — user-run

Scheduled work never prompts for a token. OTA reads its existing OS credential
store; store the current session token yourself using the hidden prompt:

```bash
.venv/bin/python -I run.py ota-token set
.venv/bin/python -I run.py schedule-worker
```

```powershell
.\.venv\Scripts\python.exe -I run.py ota-token set
.\.venv\Scripts\python.exe -I run.py schedule-worker
```

Keep this terminal/process open and the computer awake. WSL must remain running.
The worker checks every 30 seconds and reloads settings between jobs, so changes
made through another terminal take effect without restarting. It runs one job at
a time. Closing the terminal, logging out or rebooting may stop the worker; these
commands do not install a startup service, wake the computer or survive reboot.

OTA's token still expires with its session. The OS store must be available to the
worker's user session without an interactive unlock. Missing/expired credentials
fail the scheduled attempt with provider diagnostics. Scheduling cannot renew OTA
sessions or guarantee unattended daily success. Full `daily` also requires the
public-fetch dependencies. Agents prepare code/settings but never start workers
or execute due provider jobs.

For later OS integration, `schedule-worker --once` checks once and exits. Configure
a user-owned Windows Task Scheduler, launchd or Linux timer to invoke the absolute
venv interpreter and absolute `run.py` path every minute. Keep time/task selection
in this application's settings, rather than duplicating them in an OS timer.
OS task installation, logout behavior, keyring access and reboot/wake behavior
remain platform-specific setup work, not verified features of this increment.

## Pause, history and recovery

Use the same explicit interpreter as above:

```text
run.py schedule disable
run.py schedule enable
run.py schedule show
```

Disabling prevents future claims; it does not cancel a job already running. Ctrl+C
in the worker stops it and marks an active attempt cancelled where handled. Provider
captures/checkpoints and throttling cooldowns remain intact. A killed process may
leave a `running` claim; subsequent workers stop with `SCHEDULE_BUSY` until the user
confirms the old process stopped and acknowledges that job:

```text
run.py schedule acknowledge-stopped --date YYYY-MM-DD --confirm-worker-stopped
```

This marks it interrupted without replaying that day. Never acknowledge a job
whose worker is still active. Schedule edits/enabling do not retry today's previous
attempt. A failed attempt is terminal for that local day; use normal manual fetch
commands for an explicit retry. The next day's scheduled attempt remains eligible.

Late startup within the configured grace window allows one attempt. Beyond it,
today is recorded as missed. Days while the worker was entirely off are not
backfilled or recorded individually. A spring-forward nonexistent time is skipped;
a repeated fall-back time uses its first occurrence only. The recommended 05:00
example avoids these transition hours in America/Los_Angeles.

SQLite transactions prevent simultaneous claims and repeat attempts per local
calendar date in one workspace. Persisting the claim before I/O avoids automatic
duplicate requests after a crash; it does not promise exactly-once provider work.
Separate clones/machines are not coordinated. Shared provider governors still
control requests and reject overlap with a manual fetch of that provider.

Each executed scheduled job prints standard run/error log paths, its aggregate
sanitized agent-review path and the underlying provider's output/review paths.
History records UTC due/start/finish times, elapsed duration and terminal status.
Agents inspect only sanitized agent-review reports after live runs, not the SQLite
database, private logs or captures.

## Web and setup contract

`scheduling.py` owns preferences, status and claims; `scheduled_workflows.py`
dispatches allowlisted application services; `schedule_cli.py` only adapts CLI and
worker interactions. The public scan implementation is now `scan_service.py`,
shared by CLI and daily workflows, without recursively invoking the CLI.

The future personal settings page should expose time, named timezone, task,
enable/disable, grace window, next due time, history and interrupted-job recovery
through these services. Credential setup remains a separate protected local flow.
No duplicate browser scheduling logic, shell command construction or browser
credentials should be introduced. Web controls themselves remain unimplemented.
