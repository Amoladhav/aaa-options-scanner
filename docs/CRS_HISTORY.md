# CRS report history (C4a)

New catalog reports now preserve each CRS calculation revision, its source artifact
IDs, candidate settings, master version, calculation method/version, evaluation
clock, prior report and coverage counts. The existing report artifact remains the
complete authoritative result, including provider field diagnostics and raw-value
lineage. SQL stores CRS rows and metadata rather than duplicating provider payloads.
Returns are fractions; percentiles are 0–1 within stock/ETF peer groups. Excluded
members remain in history with their reason and null rank/score/return projection.

This increment applies to the localhost report builder and `report-build` shared
service. Existing standalone `dashboard`, `daily`, and `dashboard-demo` commands
still use legacy daily files. Automatic import, rollback of imports and switching
those commands to catalog history remain C4b. Older catalog reports remain readable
but do not gain invented historical rows. A newly built report records history;
opening an old report does not backfill it.

## Session selection and provenance

Every ordinary report publication retains a new revision. The last committed
non-replay report becomes canonical for its profile, price session and method.
One canonical row per session prevents same-day reruns becoming extra history days.
Synthetic/public profiles and calculation methods are separate. Prior selection
uses only sessions present in the selected price snapshot, strictly before its
cutoff. Missing intervening sessions produce `history_gap`; new members and changed
master membership are visible. No exchange calendar is fetched or inferred here.
Canonical selection is a current workspace choice, not evidence a revision was
available at an earlier trading decision. These reports are not a point-in-time
backtest. A weekend rerun retains its underlying price session.

The selected prior artifact is pinned into each report and its catalog input
lineage. Later revisions never change an existing report. Missing/corrupted prior
files stop generation rather than silently falling back to another revision.
Canonical revision selection is automatic in this increment; manual selection and
legacy import are later work. The canonical view adds no streak strategy.

`report-replay` creates another immutable report using the original source IDs,
candidate settings, evaluation time and pinned prior (including no prior). It
records the original report ID and does not change the canonical view. Evaluation
time is retained for identical freshness decisions; SQL publication time records
when the replay actually ran. Exact replay requires the same source-code fingerprint;
a changed software revision returns `HISTORY_REPLAY_VERSION_MISMATCH`. This avoids
silently claiming identical semantics after a code change. Cross-version explicit
reprocessing remains separate work. Browser display filters/column choices are
still URL state; saved screeners and selection revisions belong to C6.

## User-run commands

For the already-created synthetic web demo workspace, PowerShell:

```powershell
.\.venv\Scripts\python.exe -I -S run.py history-list --demo --profile synthetic
.\.venv\Scripts\python.exe -I -S run.py history-show --demo --report REPORT_ID
.\.venv\Scripts\python.exe -I -S run.py history-compare --demo --left FIRST_REPORT_ID --right SECOND_REPORT_ID
.\.venv\Scripts\python.exe -I -S run.py report-replay --demo --report REPORT_ID
```

Use the opaque artifact IDs from `history-list`; they differ from run IDs.
Ubuntu/WSL/macOS use `.venv/bin/python` with the same arguments. Listing defaults
to the latest 100 revisions; `--limit` accepts 1–1000. Explicit comparisons report
membership/status changes and rank differences; differing profiles/methods reject.
Different master membership is flagged, not interpreted as a price-only change.

For the regular workspace omit `--demo`. Build from explicitly indexed sources:

```powershell
.\.venv\Scripts\python.exe -I -S run.py report-build --prices PRICE_ARTIFACT_ID --ota OTA_ARTIFACT_ID --tradier TRADIER_ARTIFACT_ID
.\.venv\Scripts\python.exe -I -S run.py history-list --profile public
```

OTA/Tradier arguments are optional; there are no provider requests. Actual saved
provider data is user-run. Commands print user-facing history plus separate log,
error-log and sanitized review paths. Only aggregate counts/fixed error codes go
into agent-review files; rows and artifact IDs are not copied into those summaries.
No credential, worker or scheduler initialization is introduced.

## Upgrade and recovery

Catalog schema 2 adds `crs_runs`, `crs_results`, and `canonical_sessions`.
Initialization applies the checksummed SQL migration transactionally. Existing
files and schema-1 metadata remain unchanged; no raw sources or legacy daily files
are scanned. CRS run/row updates and deletes are rejected by SQL triggers.
Report registration, CRS rows and canonical pointer changes share one transaction.
A failure after file publication can leave an orphan file, reported by
`catalog-reconcile`; no successful history entry is published in that case.

Old software refuses a newer schema. There is no downgrade command: keep an intact
pre-upgrade copy if testing migration on an existing workspace. Managed backup and
restore tooling is C5. Do not delete schema tables to run old software. Agents only
migrated temporary synthetic databases in tests.

The service is demand-driven with no new threads, cache, polling or background
work. It adds one SQL row per master member per revision; history grows with each
report. List reads are bounded; report generation, show and compare still load
whole reports, under the existing catalog size limit. No realistic 8–16 GB resource
acceptance or new native Windows durability claim is made.

Validation: synthetic migration/rollback, atomic publication failure, immutable
rows, same-session reruns, profile/method/calendar isolation, missing/corrupted
inputs, changed membership, exclusions, replay parity and CLI review privacy.
Native Windows core/web tests and dashboard acceptance were confirmed before C4a;
this increment still needs native Windows verification. macOS remains unverified.
