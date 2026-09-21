# Project status

Updated: 2026-09-21. Phase: C6b screeners/preferences implemented; C6c durable jobs next.

Architecture/sequence clarification (2026-09-21, documentation only): CLI,
local web and cloud are required delivery targets sharing application services.
Cloud implementation remains C8; remote/multi-user operation is not implemented
or verified. C6 is sequenced as secure token onboarding, saved screeners, then
fetch controls, after C5 recovery. Major releases require cross-platform acceptance,
with native Windows verification reserved for those major releases. Local guarded
offline checks continue each increment. The specific Windows
failures were fixed; this is not a guarantee against future compatibility failures.
Keep affected Markdown documentation synchronized with each increment.

The user confirmed native Windows/Python 3.11 core tests (224, one expected
symlink skip), web tests (19 in 7.076s), successful PowerShell server/browser
startup and positive dashboard feedback, then authorized continuing. Real-data
quote coverage, actual Excel/TradingView imports, resource acceptance and macOS
remain unverified. The Windows test fixes are in commits through `5ddee40`.

C4a adds atomic append-only CRS projections for new catalog reports, one canonical
revision per profile/session/method, pinned prior-report links and exact-code
replay with the original evaluation clock. CLI history list/show/compare and
report build/replay share application services with the web builder. Schema 2
migrates metadata only; prior artifacts remain readable. See [CRS history](CRS_HISTORY.md).
C4b legacy preview/import/rollback and standalone daily workflow integration are
implemented through shared services. Schema 3 preserves immutable legacy evidence
and pinned report replay after rollback. Import controls are CLI-only; web reports
show limited legacy provenance. C5 recovery and C6 settings/jobs follow. No real database
migration, provider operation, scheduler activation or dependency install ran.
For C4a, 238 guarded core and 20 guarded web tests pass on Ubuntu/Python 3.14.4.
C4b: 249 guarded core and 21 guarded web tests pass on Ubuntu/Python 3.14.4.
Native Windows C4 verification is deferred to major-release acceptance and does
not gate C5. macOS verification and real legacy import acceptance remain pending.

The user reviewed C3a positively and approved proceeding with C3b. The localhost
dashboard now supports column-versus-value and column-versus-scaled-column rules,
nested ALL (AND)/ANY (OR), explicit parentheses and a draft/apply editor. Applied
selection is shared across table, CSV and IV-section watchlists. Legacy AND-only
URLs migrate without changing membership. Unit mismatches/unknown units reject
column arithmetic; missing operands never become zero. Original values and
candidate/scoring rules remain unchanged. See [FILTER_EXPRESSIONS.md](FILTER_EXPRESSIONS.md).

222 guarded core tests and 17 guarded web tests pass on Ubuntu/Python 3.14.4.
Coverage includes truth tables, decimal precision, missing values, unit checks,
malformed/oversized trees, old-rule migration, real form submission, draft isolation,
invalid-apply recovery and export parity. A 600-row synthetic report passes with
32 rules. Browser ergonomics, real saved quotes, Excel/TradingView import and
realistic shared-machine resource use remain pending. No live server/browser,
provider access, credential read or real-data migration ran this increment.

C5 now supplies user-run catalog backup, verification and restore through shared
services. SQLite snapshots plus immutable file manifests preserve registered
history/reports; restore validates and migrates only a fresh copied workspace.
Credentials, unindexed captures and scheduler state are excluded. 264 guarded core
and 21 guarded web tests pass on Ubuntu/Python 3.14.4, including WAL, concurrent
publication, corruption, interrupted recovery, migration and replay drills. See
[recovery scope and commands](RECOVERY.md). Native-platform and real-data recovery
acceptance remain pending; no real backup or restore was run by agents.

C6a adds shared user-run credential add/replace/remove/status, a CLI guide and a
credential-free localhost Setup page. 269 core/22 web guarded tests pass; actual
OS-store/Infisical/provider validation remains pending. No real credentials were
read or changed. See [credential lifecycle](SECRETS.md#credential-lifecycle-c6a).

C6b adds immutable named screener revisions and page-size/local-or-UTC display
preferences via shared CLI/web services. Schema 4 and C5 recovery retain revision
history and source pins; stale edits fail instead of overwriting. 276 core and
24 web guarded tests pass on Ubuntu/Python 3.14.4. Browser/real-data acceptance
remains pending. See [workspace settings](WORKSPACE_SETTINGS.md).

Next: C6c durable jobs. Finviz/IBKR stays after C6 acceptance.
Scheduling stays disabled. See [RESUME_PLAN.md](RESUME_PLAN.md).

OTA live checkpoint: the user's short-page run returned 77 rows after one page
with no error (`ec8d6c0cf18743e38ef32fa4f0832993`). This proves the observed
single-page result, not complete coverage or multi-page production behavior.
No authenticated request was executed by agents.

The token expires with the OTA session. Default fetch prompts each time; optional
native OS storage can save the current token but cannot extend its lifetime.
Manual runs and the optional local schedule worker are user-started. No login
automation or OS startup service exists.

## Current checkpoint: C3a preview

C1 is implemented (`c86eddf`), C2 onboarding docs prepared (`c7d800d`), and C3
catalog implemented (`c18ae0b`). C3a now supplies a runnable Flask/Waitress preview.
See [LOCAL_WEB.md](LOCAL_WEB.md) for exact native OS startup/stop and acceptance.
205 guarded core tests and 11 guarded web tests passed on Ubuntu/Python 3.14.4.
A separate temporary synthetic HTTP check passed health, same-origin report build,
report rendering, CSV, hostile Host rejection and clean server stop. No server
was left running. No actual browser automation/tool was available.

The user confirms the synthetic report is visible in Windows Chrome (2026-09-20).
Filtering/Excel and the user's saved OTA/Tradier quote acceptance remain pending,
as does C2's user-run Infisical/Tradier check. Native Windows Python and macOS are
unverified; basic Windows Chrome visibility after WSL startup guidance is
user-confirmed. C4 history, C5 backup/restore and C6 durable user-initiated
fetch/settings workflow remain open. C3 catalog is not a durable job queue.
Provider operations stay user-run; scheduling/hosted CI were not activated and no
Finviz/IBKR implementation began. Offline checks passed; live checks pending.

## Earlier implementation: readable run IDs and Tradier diagnostics

New run folders/logs use local YYYYMMDDHHMM plus a uniqueness suffix. Legacy IDs
remain accepted; existing artifacts are not renamed. Dashboard summaries now show
Tradier attachment and missing/failure counts. 184 isolated offline tests passed.
The reviewed Tradier batch summary reports 554 received and 10 failed out of 564;
attachment to the user's new dashboard remains to be verified by a user-run report.

## Previous increment: interactive CRS tail selection

HTML now offers top/bottom/both X-percentile controls and explicit CRS ordering,
with field-diagnostic help and Tradier attachment counts. Presentation filters do
not change rankings, fixed 10% labels, candidate rules or CSV files. 182 isolated
offline tests passed; browser interaction and real-data report checks remain pending.

## Previous increment: CRS with complete OTA columns

The combined HTML and Excel-readable master CSV now include CRS score, rank,
percentile, 21/63/126-session returns and all captured OTA source fields. Raw
values remain separate from interpreted filter metrics. The master remains the
driver; outside-master OTA rows are counted and remain in the standalone inventory.
Original OTA values are retained in the copied dashboard input.
181 isolated offline tests passed, including a synthetic 5,642-row OTA join,
unchanged CRS ranks, missing-price rows and spreadsheet/HTML escaping. The
synthetic dashboard CLI ran successfully. Real-data combined output and interactive
browser validation remain user-run and pending; strategy performance is unvalidated.

## Previous increment: comprehensive OTA saved-data reports

Console preview, paginated/searchable HTML, all-row CSV/JSON, symbol export and
field-quality details are available through `ota-report`. The source snapshot is
preserved byte-for-byte in each report bundle; incomplete inputs fail explicitly.
Shared model/options/services prepare future web reuse. 176 isolated offline tests
passed, including 5,642-row parity. The synthetic CLI preview ran successfully;
interactive browser and live-data checks remain pending. No provider data was
read or fetched by the agent. See [OTA reports](OTA_REPORTS.md).

## Previous increment: personal local schedules

Reusable personal schedule settings and SQLite daily claims support time/timezone,
OTA or daily workflow, enable/disable, next due time, grace windows and history.
Interrupted claims require explicit acknowledgement; no automatic same-day replay.
Public scan execution is extracted into a shared application service. Setup-agent,
manual setup and future web-control requirements are updated; see
[Scheduling](SCHEDULING.md). 167 isolated offline tests passed. No worker or provider
request was started by the agent; native OS timer/keyring and web checks remain pending.

## Previous increment: larger OTA pagination budget

OTA fetch and daily commands default to a 100-page safety ceiling, retaining
100 rows per page and short-page termination. Synthetic regression coverage
collects 5,642 unique rows in exactly 57 requests. Save/fetch stdout now identifies
the absolute config path and criteria fingerprint; sanitized fetch reports carry
the fingerprint, criteria counts and page settings. 154 offline tests passed,
including apply-to-request body parity. The reported live 77-row short page is
not a page-limit failure. Config identity diagnostics support the next user-run
comparison; the expanded screener has not yet been verified live.

## Previous increment: conservative provider throttling

Shared request pacing now covers OTA, Tradier and public-fetch transports, with
local ignored feedback/history, conservative ETAs and bounded GET retries. See
[throttling](THROTTLING.md) for defaults, stopping rules and operational limits.
152 offline tests passed using the isolated standard-library runner. No live
provider calls were executed; optional yfinance backend and live pacing checks
remain user-run and pending.

## Implemented

- Independent Git repository with origin; no agent pushes or authenticated calls.
  User setup commits `89dd8c8` and `cd9567b` are preserved. Initial scanned
  momentum reference commit: `cba570f`.
- Narrow reference baseline: three accepted files, 432 excluded. Full path/hash
  manifest and value-suppressing finding disposition are recorded. Raw INBOX is
  unchanged; excluded material remains unapproved. Redistribution rights unresolved.
- Pure standard-library momentum core: 21/63/126-session adjusted returns,
  50/25/25 weights, three-sigma clipping, stock/ETF peer groups, tied midranks,
  finite-price validation, missing/stale exclusions and minimum group size 20.
- Explicit synthetic demo, cached replay, sortable/filterable HTML, full master
  universe CSV, ranking/exclusion CSVs, immutable per-run JSON snapshots and hashes.
- User-run public adapter: Wikipedia current S&P membership; 11 sector ETFs and
  50 starter ETFs including SPY; yfinance adjusted daily prices; XNYS completed
  sessions with one-hour close buffer. No real provider execution by an agent.
- Allowlisted agent-review summaries and sanitized failures; no synthetic fallback
  on public-data failure. Third-party provider output is discarded, not captured.
- Standard stdout stage messages and per-stage bars for every scan command; public
  downloads report completed batches. Structured per-run JSONL logs are flushed
  at each event, with safe timings/counts, failures, warnings and Ctrl+C cancellation.

## Verification

On Ubuntu, Python 3.14.4: seven intake-tool tests passed at the prior checkpoint. The current guarded
application-suite result is recorded in VALIDATION.md. The offline runner denies network, subprocesses, real environment reads,
and files outside reviewed source/tests/config, stdlib and a synthetic temp tree.
Guards are installed before test discovery. Tests cover numeric reference parity
on complete untied inputs, ties, weights, endpoints, missing/nonfinite prices,
future-data exclusion, split-adjusted constant prices, session close buffers,
holiday/weekend schedules, group separation, provider batch orchestration with
synthetic responses, HTML/CSV escaping and diagnostic allowlists.
Progress/logging tests verify stdout visibility during provider suppression,
immediate flushing, schemas, empty batches, safe failures, cancellations,
exclusion warnings, cached profile resolution and preservation of earlier logs.

Commands from project root:

```bash
python3 -I -S tools/test_intake_scan.py
python3 -I -S tools/test_offline.py
python3 -I -S run.py demo
```

See [README](../README.md) for native Windows and user-run public setup commands.
See [validation record](VALIDATION.md) for scan disposition and commit sequencing.
No incoming application code was executed. The new active implementation is the
only runtime source; reference tests are never collected. No third-party packages
have been installed by the agent. Direct dependency pins are documented; a full
transitive lock and installation verification remain pending.

Offline checks passed; live checks pending. Tests do not prove real provider
access or strategy performance. Native Windows/macOS, browser interaction, remote CI execution,
hooks, and WSL-specific checks remain pending. Hosted CI is deferred; the former workflow is retained only as an inactive
example under docs/future-ci/. Verification runs locally.

## Decisions and limits

- User confirmed cross-sectional momentum, not strength relative to SPY.
- Exact 21/63/126-session horizons replace Finviz performance period fields.
- Missing values are excluded rather than imputed; ties receive equal percentiles.
  Scores compare valid members only; exclusions can change the comparison universe.
- Stock and ETF rankings are separate. Sector ETF view is a filtered ETF ranking.
- The 50-ETF selection is a configurable starter watchlist, not verified current
  options-volume leaders. Current symbol/fund and options liquidity checks pending.
- Current membership snapshots are not historical universes for backtesting.
- Current snapshot acquisition gets a full history each refresh; cached replay is
  offline. Incremental download merging is deferred to avoid stale adjustments.
- Offline options enrichment supports separate supplied IV metrics, volume and open
  interest, synthetic examples, CSV/HTML output and deterministic snapshot replay.
  Single-page live OTA access is verified. Session rank history is implemented; no Conviction score, order
  execution or performance claims.
- OTA row parsing is tested with invented fixtures. Vendor fields remain separate
  from normalized IV metrics. Pagination defaults to 100 rows, up to 50 pages,
  and stops on a short page. Duplicates, page limits and mid-run failures
  retain incomplete raw captures without publishing completed results. Live paging, timestamps and repeat-run validation remain pending.
- `ota-config` accepts complete pasted criteria, previews a versioned config and
  atomically replaces `config/ota-screener.json` with `--apply`. It uses shared
  progress/logging and never executes pasted code or makes provider requests.

## Current increment

- Combined cached CRS/OTA HTML and CSV report, explicit missing/stale states,
  unchanged CRS scores, settings-based unverified shortlist.
- Configurable volume/OI/vendor-liquidity/earnings/mean-IV thresholds; preserved
  vendor fields and separate price-age/retrieval-age limits.
- Session history with rank movement, entrants/departures and gaps; repeated
  runs replace the same session. Synthetic and public histories stay separate.
- Daily user-run refresh/fetch/report workflow stops on failure without old-data
  fallback. Cached dashboard reuses local data without downloads.
- Optional native OS storage for OTA and separately profiled Tradier credentials.
- Standalone monthly ATM Tradier probe prepared with pure selection/spread tests;
  dashboard integration waits for the user's draft approval. Bid, ask, OI and
  current volume per leg; average contract volume unavailable.
- Source access inventory: [SOURCES.md](SOURCES.md). Metric definitions stay
  explicitly unverified. [CHAIN_PLAN.md](CHAIN_PLAN.md) records monthly rules.

## Remaining external validation

1. User reviews the synthetic dashboard and runs cached dashboard on real files.
2. User validates fresh daily output and optional OS credential store locally.
3. After draft approval, user tests the isolated Tradier probe; integrate its
   contract metrics only after schema, expiration, delay and quote times check out.
4. Verify live OTA full-page continuation, metric definitions and a defensible
   options-volume ETF universe. Current 50 ETF list remains a starter watchlist.
5. Defer hosted CI until explicitly requested; confirm native OS behavior locally. No performance or
   profitability validation is claimed.

## OTA capture redesign

Capture preserves bounded response bodies and original row values; field-type
profiles and versioned normalization are separate outputs. `ota-process` replays
local captures without network/authentication. Dashboard accepts completed raw
captures and exposes processing statuses; incomplete runs cannot become reports.
125 guarded offline tests passed, including byte preservation, mixed-field profile
counts, partial failure retention, sanitized profile summaries and offline replay.
Legacy files remain readable but cannot restore previously discarded values.

## Shared ingestion policy adoption

Policy revision 3 applies capture/profile/normalize/business-rule separation to
all external fetches, including public library adapters. OTA implements the first
capture/profile/replay increment. Tradier now has initial raw-body capture and field profiles; replay and broader
normalization remain pending. Public price/constituent adapters still need adoption; cross-run schema-drift comparison and retention controls
are requirements, not implemented features. Library-returned data cannot be
claimed to preserve wire-level bytes unless the actual transport exposes them.
Agents must explain applicable established practices and project-specific
tradeoffs when analyzing requirements and recommending solutions.

References: [layered raw/refined/business data](https://learn.microsoft.com/en-us/azure/databricks/lakehouse/medallion)
and [schema evolution and rescued fields](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/schema).
These are established architectural patterns, not a mandate to adopt Databricks
or a universal requirement to accept unusable data into calculations.

### Saved Tradier dashboard integration — 2026-09-19

Added repeatable `dashboard --tradier PATH` for explicitly selected saved ATM
probe outputs. HTML/CSV show strikes, monthly expiry, quotes, spreads, liquidity,
Greeks and profile/retrieval provenance. Duplicate symbols, mixed environments
and provider data in synthetic dashboards are rejected. Missing data remains
blank and freshness unverified; CRS and candidate rules are unchanged.
129 guarded offline tests passed on local Python, including cached CLI integration,
HTML escaping, preserved Greek strings, missing legs' Greeks, profile separation
and unchanged ranks. User-run combined dashboard validation remains pending.
Automatic batch collection, daily Tradier orchestration and quote freshness
validation remain pending.

### Master-driven collection — 2026-09-19

`tradier-fetch` now drives sequential, paced collection from all members of an
explicit/latest public snapshot, independent of CRS and OTA filters. Shared probe
capture/selection retains raw responses and profiles; a hidden key is loaded once.
Per-symbol checkpoints preserve successful, failed and unattempted members. Local
schema/selection errors continue; systemic failures stop. No automatic resume.

Dashboard joins now retain every master member, including CRS exclusions, and
accept explicit `batch.json` with matching master membership hash. Provider
columns/statuses remain separate; no implicit universe expansion or quote-based
ranking changes. `master.csv` is the enriched full-universe export.
136 guarded offline tests passed locally, covering batch success, raw captures,
share-class mapping, partial errors, auth-stop checkpoints, single credential
prompt, paced requests, master mismatch and retention of unranked members.
Live full-universe collection and dashboard batch validation remain user-run and
pending. Daily orchestration of Tradier, resume, freshness validation and automatic
cross-run profile drift comparisons remain pending.


### Structured local-time logging and terminal progress — 2026-09-19

Shared progress now refreshes one line on interactive terminals, retains plain
lines when redirected, and clears the display for prompts and errors. Tradier
batch substeps identify expiration/quote/chain work. Stdout uses OS local time
with offset; log schema 2 retains UTC and adds local timestamp, zone label and step.
Every run prints full-log and warning/error-log paths at startup and completion.
Final summaries show status, elapsed time and available aggregate operation counts.
Tradier per-symbol errors are recorded as safe codes without source identifiers.
140 guarded offline tests passed, including synthetic TTY redraw/prompt behavior,
redirected output, error log/privacy boundaries, partial summaries and local offset
conversion across a date boundary. Actual user terminal rendering and native
Windows/macOS verification remain pending; no credentialed fetch was executed.


### Local verification only — 2026-09-19

Removed the push/pull-request workflow from the active GitHub Actions directory.
Its six-job matrix is retained as docs/future-ci/offline.yml.example for later
review. Shared policy revision 5 requires explicit user activation of hosted CI.
Local tests remain unchanged. The remote workflow may remain enabled until the
user disables it on GitHub or pushes the local removal; no remote action was
performed by the agent.


### Future architecture planning — 2026-09-19

Added [the future-enhancement planner](FUTURE_ENHANCEMENTS.md): incremental service
extraction, durable local jobs/metadata, a personal local web interface, local
hardening and an explicitly deferred multi-user/cloud gate. It maps current modules
to responsibilities and specifies compatibility, verification and recovery criteria.
Shared policy revision 6 and scanner instructions require proportional assessment
of every request against the roadmap, with material decisions recorded and no
speculative infrastructure. This increment changes documentation only; no web
server, database, worker, account system or cloud component was added.


### Adaptive setup and continuing user feedback — 2026-09-19

Added [interactive setup-agent instructions](SETUP_AGENT.md) and a
[manual first-run guide](SETUP.md) covering PowerShell, macOS Terminal and Ubuntu/WSL.
The role adapts beginner/guided/concise detail and begins with a synthetic demo;
it is documentation for a repository-aware assistant, not a standalone executable.
Shared policy revision 7 requires a relevant next-step recommendation and user
feedback invitation at completed-task milestones. README and the future planner
link onboarding to the local-web direction. Documentation/static checks only;
novice walkthroughs and native OS setup execution remain pending.

## Research handoff prepared

[IMPLEMENTATION_RESEARCH.md](IMPLEMENTATION_RESEARCH.md) records official-source
findings for Infisical, Flask/Waitress, SQLite and later Finviz/IBKR adapters. It
includes test-isolation constraints and current code pointers. Research only; no
dependencies, provider access, database migrations or server startup performed.

## C1 shared credential loader — 2026-09-20

Implemented explicit env/store/prompt/auto resolution in `credentials.py`, with
provider/profile separation, absence-only fallback, hidden TTY prompts and safe
errors. CLI adapters share it; existing OS-store commands/defaults are preserved.
`credential-check` writes an allowlisted format-check report without contacting a
provider. No import-time environment access; domain/provider clients still receive
explicit credential strings. No dependency or scheduling changes.

192 guarded offline tests passed on the local Ubuntu interpreter, including
precedence, malformed/missing input, no-TTY/echo-warning failures, one-key reads,
CLI redaction and auth-failure behavior. Offline checks passed; live checks pending.
Infisical installation and Windows/macOS verification remain user-run and pending.

## C2 Infisical onboarding — 2026-09-20

[SECRETS.md](SECRETS.md) now documents reviewed official installation URLs,
separate OS commands, explicit environment/folder/profile wrappers, format checks,
renewal/revocation and keyring limitations. No installation or authentication ran.
C1's 192 synthetic tests cover the CLI contract; docs/links/commands reviewed.
User-run Tradier-through-Infisical and Windows/macOS/WSL verification remain pending.
Proceeding with credential-free C3/C3a does not close that acceptance gate.

## C3 local artifact catalog — 2026-09-20

Implemented checksummed transactional SQL migrations, immutable file publication,
run/input metadata, initial settings/master tables, explicit saved-source indexing
and aggregate reconciliation. Existing scheduler DB/schema remain untouched.
201 guarded offline tests passed, including rollback/upgrade, foreign keys,
byte-preserving idempotent indexing, interrupted publication, missing/changed
files and path confinement. Only temporary synthetic databases were opened.
See [CATALOG.md](CATALOG.md) and [decision 0001](decisions/0001-local-catalog.md).
C3a preview is next; C4 history and C5 backup/recovery remain pending.

## C3a shared saved-report web interface — 2026-09-20

`report_service` centralizes CLI/web composition, validated complete-dataset view
selection and formula-protected CSV. The local app adds source pickers, report and
run pages, coverage/diagnostic details and full/filtered downloads. A dedicated
synthetic workspace avoids reading user artifacts on demo startup. It checks exact
loopback Host/Origin, CSRF, proxy headers, escaping and safe errors; no credential,
provider, raw-capture, scheduling or arbitrary filesystem routes exist.

Web reports currently omit prior daily-history input, explicitly documented until
C4. Existing CLI history remains compatible. Code revision hashes now include
web templates/assets and SQL migrations as well as application Python. Pinned
web extras and a separate guarded runner preserve the default core isolation.
See [dependency review](WEB_DEPENDENCIES.md) and [decision 0002](decisions/0002-local-web-preview.md).

## Shared-machine resource review — 2026-09-20

User requests low CPU/memory overhead alongside TradingView, TOS and other apps.
The owner has 32 GB RAM; the design target is shared 8–16 GB machines. Acceptance
on that hardware and a realistic-workload resource budget remain pending.
Synthetic 60/600-symbol checks (150 sessions) observed about 46/58 MiB peak Python
process RSS and 29/85 ms report builds. These in-process figures exclude Chrome,
the full WSL VM and real-provider payloads. No runtime settings or global resource
limits changed. Full-report decode on every view and in-memory CSV are known
scaling limits; retain on-demand behavior and assess richer inputs before C6.
See [resource evidence and limits](LOCAL_WEB.md#resource-use-and-shared-machine-constraint).
