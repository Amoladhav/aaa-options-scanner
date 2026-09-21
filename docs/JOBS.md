# Durable local jobs (C6c)

CLI and localhost **Jobs** use one service for submission, inspection and
cancellation. Submission stores an immutable request; it never starts a worker or
reads credentials. A foreground `job-run --job ID` executes exactly that job.
There is no daemon, automatic retry, browser execution route, polling, scheduler
activation or hosted CI. Provider execution remains user-run.

Supported requests are report build, OTA fetch and Tradier master fetch. Reports
pin catalog inputs, filters, prior history and evaluation time at submission.
OTA pins the validated saved configuration and page limits. Tradier pins a public
price master, explicit sandbox/production profile and observation date. Provider
jobs store only an `env` or `store` credential reference; the user-started worker
resolves it with prompting disabled. See [credential setup](SECRETS.md).

## Use

Open **Jobs** in the local dashboard, select sources and queue work. Refresh the
page manually to see its state and latest 100 events. Provider submission is
unavailable in `web --demo`. Normal web mode allows submission but still cannot
execute provider work. Choose the credential source and Tradier profile explicitly.
The job page gives commands using the selected job ID. For example, from the
project directory with your own environment already set up:

Ubuntu/WSL:

```bash
.venv/bin/python -I run.py job-list
.venv/bin/python -I run.py job-show --job JOB_ID
.venv/bin/python -I run.py job-run --job JOB_ID
.venv/bin/python -I run.py job-cancel --job JOB_ID
```

Native Windows PowerShell (separate native virtual environment):

```powershell
.\.venv\Scripts\python.exe -I run.py job-list
.\.venv\Scripts\python.exe -I run.py job-show --job JOB_ID
.\.venv\Scripts\python.exe -I run.py job-run --job JOB_ID
.\.venv\Scripts\python.exe -I run.py job-cancel --job JOB_ID
```

Replace `JOB_ID` with the non-secret ID printed by submission. Add `--demo` to
every job command for the separate demo workspace. Provider submission rejects
that flag. macOS uses the POSIX command form but remains unverified.
CLI equivalents to the forms (use the interpreter above):

- `run.py job-submit-report --prices ARTIFACT_ID [--ota ARTIFACT_ID] [--tradier ARTIFACT_ID]`
- `run.py job-submit-ota --credential-source env --page-size 600 --max-pages 50`
- `run.py job-submit-tradier --prices ARTIFACT_ID --profile sandbox --as-of YYYY-MM-DD --credential-source store`

Submission prints a job ID. Optional `--action-key` takes a 32-character lowercase
hex action ID: repeat the same request/key to get the same job; different requests
with that key conflict. A new action ID intentionally creates new work. The web
form supplies an action ID to prevent duplicate browser resubmission.

## Lifecycle and recovery

SQLite transactions and a unique active-worker constraint allow one `running` or
`cancel_requested` job per workspace. Pending jobs do not consume a worker. A code
content hash must match the submitted request before claim; after updating the
application, cancel old queued work and submit a new reviewed request.

Queued cancellation is immediate. Running cancellation is cooperative between
requests/pages/symbols, during pacing waits, and before final publication. It
cannot undo an in-flight HTTP request or durable output. Completed publication
wins a later cancellation. Provider governors retain their existing cooldown,
retry and lock rules. Failed/cancelled captures stay in private local storage;
only complete OTA data and completed/partial Tradier batches are indexed.

Terminal states are succeeded, partial, failed, cancelled and interrupted.
Errors use fixed codes; job events contain allowlisted stages/counts and UTC times.
The UI renders local time or the saved UTC preference. Logs and sanitized review
reports use the existing shared progress component. Ordinary job inspection may
show request criteria and artifact IDs; agents inspect only intended sanitized
review reports after real user runs.

After a crash, no job is automatically resumed. Confirm the worker has stopped,
then run `run.py job-recover --job JOB_ID --confirm-stopped` with the selected
interpreter and workspace flag. This marks it interrupted and fences the old
worker from publishing job state. It does not undo completed requests. Inspect
saved outputs before submitting a new action; an output may exist if a process
stopped between publication and recording terminal job state. Existing throttle
locks are not removed by recovery; follow [throttling](THROTTLING.md).

Schema 5 adds jobs, immutable requests, pinned input relationships and append-only
events. [Catalog backups](RECOVERY.md) include these rows and indexed outputs.
Restore preserves queued/running states and never starts workers. Do not run an
original and restored workspace against the same provider concurrently: worker
and provider locks coordinate one workspace only. Private captures, credentials,
provider pacing files and ordinary logs remain outside catalog backup scope.
No automatic event retention/deletion is configured. Lists cap at 1,000 jobs and
100 recent events; storage grows with actual user-run work. Reports and source
snapshots retain the existing in-memory size limits; realistic resource acceptance
for combined web/worker use on shared 8–16 GB machines remains pending.

## Evidence and remaining acceptance

289 guarded core and 26 guarded web tests pass on Ubuntu/Python 3.14.4. Synthetic
checks cover immutable/idempotent submission, one-worker claims, cancellation,
interrupted recovery and stale-worker fencing, version mismatch, backup state,
pinned provider inputs, OTA success/cancel, Tradier partial output and web CSRF.
No credentialed worker or real provider request was run by an agent. Native
Windows verification remains at major releases; macOS, real-provider acceptance,
Excel/TradingView imports and realistic resource checks are still pending.
C6 user acceptance is required before C7 Finviz/IBKR implementation.

## C6 review without provider access

Using the existing demo workspace, open **Setup** and change page size, save a
report view under **Screeners**, then open **Jobs** and queue a report with the
synthetic price/OTA sources. Run the exact demo command shown on its job page.
Refresh **Jobs**, open the completed output, and compare its sources and selected
rows with the original. Queue a second report and cancel it before execution;
its state should become cancelled without an output. Review labels and workflow
for usefulness. This can be done on the existing verified setup; it does not
require an intermediate native Windows re-test or any credentials.

Start the synthetic dashboard, if it is not already running, with
`.venv/bin/python -I run.py web --demo --port 8765` on Ubuntu/WSL, or
`.\.venv\Scripts\python.exe -I run.py web --demo --port 8765` in native PowerShell.
Open `http://127.0.0.1:8765` and stop with Ctrl+C. Do not start another server on an
occupied port. User acceptance of this workflow is separate from pending real
provider and release-platform checks.
