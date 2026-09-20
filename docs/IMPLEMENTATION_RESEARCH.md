# Implementation research for the next agent

Checked 2026-09-20 against public primary documentation and repository source.
Read [RESUME_PLAN.md](RESUME_PLAN.md) for ordering and acceptance gates. This is
research and proposed design, not installed dependencies or live validation.
Recheck versions, licensing, installation URLs and provider access at implementation.
No secrets, account operations, raw data inspection or installs were performed.

## Recommended stack and why

Recommendation: Flask + Jinja templates + minimal local JavaScript + Waitress;
Python sqlite3 with explicit migrations; Infisical CLI outside application code.
No Node build, Redis, container requirement or ORM for the first local release.
This is a project recommendation, not a requirement imposed by the frameworks.

Flask's test client exercises requests without a running server, fitting our
synthetic route-test approach. Its security guide covers escaping, CSRF, resource
limits and trusted hosts; these need configuration and tests, not assumptions.
Use an app factory with explicit workspace/services and no import-time I/O.
[Testing](https://flask.palletsprojects.com/en/stable/testing/),
[security](https://flask.palletsprojects.com/en/stable/web-security/).

Waitress is a pure Python WSGI server with native Windows support, one process
and multiple worker threads. Bind explicitly to 127.0.0.1; do not use a debug
server/reloader for the user's regular workflow. Put long fetches in the durable
job worker, not web threads. Bounded polling is enough for initial progress.
[Waitress deployment](https://flask.palletsprojects.com/en/stable/deploying/waitress/).

Alternative researched: Starlette/FastAPI-style ASGI. Starlette supplies escaped
Jinja templates and an in-process test client, but asynchronous lifecycle and
additional dependencies are not needed for our first synchronous saved-data UI.
Reconsider if streaming/websocket needs justify it; do not implement both stacks.
[Templates](https://www.starlette.io/templates/),
[test client](https://www.starlette.io/testclient/).

Dependency work: repository currently has requirements-public.txt,
requirements-keyring.txt and requirements-scheduling.txt; no pyproject.toml.
Add a separately pinned web dependency set only after reviewing versions and
licenses. Preserve standard-library-only core operation. No dependencies installed
or exact compatible versions selected by this research.

## Critical offline-test integration work

`tools/test_offline.py` installs guards before collection: denies sockets,
subprocesses, environment reads, unapproved filesystem paths and real SQLite DBs.
It also excludes site-packages. A Flask test cannot simply be added to this suite
and expected to import successfully. Do not disable the guard to get tests green.

Prepare a separate reviewed web test runner with allowlisted pinned dependency
paths, synthetic settings/environment, temp-only SQLite and the same network,
process and credential restrictions. Inspect transitive imports before execution.
Use in-process requests. The default core suite remains independent of web extras.
Browser/OS smoke tests are separate; only synthetic content may be agent-tested.
User tests real reports. Existing baseline: 184 isolated tests, runtime ec66c33.

## C1/C2: Infisical implementation notes

The official repository describes an MIT core with separately licensed enterprise
features. Managed hosting is optional; it stores secrets remotely. Self-hosting
requires operations work and is not the beginner default.
[License/repository](https://github.com/Infisical/infisical).

The CLI can inject environment variables into a child process, scoped using --env
and --path. Use explicit profile and environment; do not rely on a default that
could select the wrong secrets. Avoid --watch for fetches: restarting could repeat
work. Login stores authentication in a local keyring, so do not claim everything
is memory-only. Machine-identity login can print tokens: do not copy those example
commands into logs or novice setup. Use browser login for initial personal setup.
[Run](https://infisical.com/docs/cli/commands/run),
[login](https://infisical.com/docs/cli/commands/login).

Official installation starting points (user-run; recheck before publishing guide):

- macOS: `brew install infisical/get-cli/infisical`.
- Windows with Scoop already installed: `scoop install infisical`; otherwise use
  the official release binary and verify published integrity information.
- WSL Debian/Ubuntu: official Linux repository setup then apt installation.
  Current CLI repository says packages moved to artifacts-cli.infisical.com and
  the old Cloudsmith host stopped service on 2026-09-16. Download and review the
  setup script before privileged execution; do not blindly pipe it to sudo bash.
- `infisical login`, then `infisical init` in the project: user executes both.
  Review local project metadata before tracking; no authentication data in Git.

[CLI repository/install instructions](https://github.com/Infisical/cli).

Proposed wrapper after C1 exists: `infisical run --env=dev --path=/scanner --
.venv/bin/python -I run.py ...`; PowerShell uses `.\.venv\Scripts\python.exe`.
This is a template, not a currently supported environment-credential command.
Add exact provider/profile/source arguments once implemented. Python -I ignores
Python configuration environment variables, not explicit application os.environ
reads. Do not use dotenv exports or shell token substitutions in examples.

Current token boundary: token_store.py validates printable tokens and selects
native keyring backends; OTA prompt lives in ota_fetch.py; Tradier uses
prompt_api_key/load_token. C1 should centralize resolution without changing the
provider clients' existing validation or safe failure behavior. Existing keyring
failure on WSL motivates env injection but does not establish Infisical login
will work there; test its actual keyring setup.

Infisical has Render and AWS Secrets Manager sync endpoints. Their existence is
not evidence the user's plan/account is entitled or configured. Verify connector
permissions, deletion/overwrite settings and redeployment before activation.
[Render sync reference](https://infisical.com/docs/api-reference/endpoints/secret-syncs/render/import-secrets),
[AWS sync reference](https://infisical.com/docs/api-reference/endpoints/secret-syncs/aws-secrets-manager/list).
ECS injects secrets at task startup; rotation requires task replacement. Do not
promise live refresh of os.environ. [ECS guide](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html).

## C3/C4/C5: SQLite implementation notes

Use short transactions and one connection per service operation/thread, not a
shared global connection with thread checks disabled. Bind SQL parameters; never
interpolate filters or user paths into SQL. Set explicit transaction semantics
rather than relying on changing Python defaults. Use Connection.backup for a
coordinated backup and verify restore. [Python sqlite3](https://docs.python.org/3/library/sqlite3.html).

Start with the default journal unless measured workload justifies WAL. WAL allows
read/write overlap but still one writer, needs sidecar/checkpoint handling and
same-host storage. Review the current SQLite WAL bug/version guidance before
choosing it; Python's bundled SQLite version varies by OS/runtime. Record
sqlite3.sqlite_version during synthetic environment checks. Do not put a live DB
in a network share or cloud-sync folder. [WAL](https://www.sqlite.org/wal.html),
[deployment](https://www.sqlite.org/whentouse.html),
[backup](https://www.sqlite.org/backup.html).

Current scheduling database is artifacts/scheduler/schedule.sqlite3, user_version
1, with settings and jobs tables. ScheduleService.connection() opens/closes per
operation and rolls back outstanding transactions. It is daily-claim scheduling,
not a general-purpose run/history database. Preserve it until an explicit tested
migration; a new catalog must not start a second scheduler.

History currently uses dashboard.history_previous/save_history; same-session
files are overwritten intentionally to avoid artificial streaks. New append-only
history must retain every run while preserving one canonical selection per session.
See resume plan for tables and gates. No actual user DB was opened for research.

## C3a: concrete web service and route proposal

Names below are design proposals, not existing commands/routes.

- create_app(workspace, report_service, catalog, credential_resolver).
- GET /health: fixed healthy/version response; no environment/config dump.
- GET /: source selection and safe source/coverage metadata.
- POST /reports: validate source IDs, master/profile compatibility, create saved
  report through shared service; no provider fetch implicit in generation.
- GET /reports/<id>: paginated master table, full-dataset filters and source badges.
- GET /reports/<id>/export: allowlisted csv download, full versus filtered explicit.
- GET /runs and /runs/<id>: run history, provenance, counts and safe errors.
- Later POST /jobs, POST /jobs/<id>/cancel and GET /jobs/<id>: C6 durable execution.

Use allowlisted artifact IDs resolved within the workspace, prevent symlink/path
escape, and validate query limits and sort names. Separate read-only views from
mutations; CSRF protection and trusted Host/Origin checks still matter on localhost.
No broad CORS, no raw artifact static mount, no browser credential entry in v1.
Use local assets and escaped text. Avoid logging query bodies/private source data.
The current inline HTML filter logic should become a shared selection contract
with parity tests so filtered CSV and table select exactly the same rows.

Code map: dashboard.combine/attach_tradier/write_dashboard, workflow.run_dashboard,
ota_report_service.generate_report, ota_reporting model/cell, progress.RunProgress,
run_ids, throttling, scheduling.ScheduleService. First extract reusable report
composition from CLI printing/argparse/history side effects; do not call CLI main
from HTTP routes. Run IDs are labels, not the source of chronology.

## C7: sources grouped by access

### Public browsing / no authenticated API established

Finviz public pages can be browsed, but that is not an open API contract. No
account-free official API was established in this research. Do not substitute
scraping, cookie extraction or a third-party wrapper for documented API access.

### Account, login and/or paid entitlements required

**Finviz Elite:** official FAQ explicitly includes export/API access with Elite.
The API-and-exports link could not be retrieved with this research tool; exact
endpoint schema, authentication, rate limits, retention and redistribution remain
unverified. Do not invent them. User should supply a public documentation link or
access type later, never a tokenized export URL. First increment can be a user-run
saved CSV importer, then authorized API acquisition after the contract is known.
[Official FAQ](https://elite.finviz.com/help/faq).

**IBKR:** official individual Web API guidance requires a fully open funded Pro
account, including access associated with paper trading. Market data needs the
relevant subscriptions/permissions and authenticated sessions. A username can have
one brokerage session at a time; connection choices can affect another logged-in
platform. Confirm current account eligibility and auth route with the user's
account context before implementing. [Web API access](https://www.interactivebrokers.com/campus/ibkr-api-page/web-api-trading/).

Two separate IBKR adapter candidates:

- TWS API: socket API through Trader Workstation or IB Gateway. Investigate first
  if user already runs either; keep read-only configuration and omit order methods.
  Do not confuse IB Gateway with the Client Portal Gateway.
- Web API: HTTP/WebSocket; Client Portal Gateway uses a local service by default.
  OAuth/direct-access suitability depends on onboarding/auth model. Do not assume
  a generic long-lived API key or automatic headless login. Do not copy examples
  disabling TLS verification into a general HTTP client.

[Current API index](https://www.interactivebrokers.com/docs),
[Client Portal base URL](https://www.interactivebrokers.com/docs/web-api/v1/endpoints/introduction).

IBKR quote requests can need a preflight followed by later reads; an initial empty
quote is not necessarily missing coverage. Greeks can arrive later. This requires
bounded warm-up state, timeouts and partial-field capture, not fabricated zeros.
Expired-option data and historical Greeks have limitations; do not promise a
historical options backtest dataset from this connection.
[Market-data lesson](https://www.interactivebrokers.com/campus/trading-lessons/requesting-market-data/).
TWS option discovery includes reqSecDefOptParams; resolve exact contracts before
requesting quotes, rather than retrieving every possible strike for every symbol.
[Current TWS reference](https://www.interactivebrokers.eu/campus/ibkr-api-page/trader-workstation-api/).

Use master-driven symbol/conid mapping with exchange/currency/trading-class and
multiplier checks. Compare the exact monthly expiration and shared ATM strike to
Tradier. Keep bid/ask, quote timestamps, live/delayed status, OI and volume distinct;
verify average-volume period and Greek units before comparing providers. Test a
few symbols first, then a bounded batch with existing pacing. Account numbers,
positions, orders and transfers are not needed for the intended data enrichment.

## Open questions to resolve only when their checkpoint begins

- Infisical managed versus self-hosted choice, region, CLI keyring availability and
  environment names; no need to request these before C1 synthetic implementation.
- Web dependency versions/licenses and guarded optional-test runner approach.
- Database retention period, backup destination and selection rule for canonical
  same-session results; preserve current behavior until explicitly changed.
- Finviz account tier and official export contract; IBKR account/auth setup and
  market-data subscriptions. Ask access types only, never identifiers/secrets.
- Native Windows/macOS/browser validation environments. Do not mark portability
  verified merely because library documentation lists those platforms.

The next agent should start C1, not repeat broad research or activate C7 early.
Follow source links only when resolving an implementation-specific uncertainty.
