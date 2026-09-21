# Saved screeners and display preferences (C6b)

CLI and localhost controls use one `WorkspaceSettings` service. Schema 4 stores
immutable, checksummed revisions and separate current pointers in the catalog.
These are private workspace data, included in C5 catalog backups; they never belong
in source defaults or credential storage. No provider request, scheduler, worker,
or cloud deployment is activated by saving or applying a view.

## Local web

On a report, apply the desired filters/columns/order, then expand **Saved screeners**.
Choose **Create new** and enter a name, or select an existing screener to update and
leave the new name blank. Save persists the applied view; unapplied expression
editor drafts are excluded. Use **Apply saved revision** to reuse a screener on
another report. **Screeners** lists current definitions and earlier revisions;
a historical revision can be reopened on its source report. There is no delete or
automatic pruning in this increment.

Saved views include search, peer group, CRS tail/percent, sort/direction, page size,
visible columns and the versioned expression tree. Legacy AND filters normalize
to that tree. The page resets to 1. Applying a screener requires its referenced
columns to exist; missing provider fields produce an error rather than silently
removing rules. Applying does not rerun ranking or change immutable report data.
Table, filtered CSV and watchlist continue to share membership/sort evaluation.
Presentation rules are not financial eligibility or calibrated strategy signals.

**Setup → Display preferences** persists default page size (25/50/100/250) and
machine-local versus UTC timestamp display. Local time uses the runtime machine's
configured timezone/DST, which can differ from the browser machine. UTC has no DST.
Explicit report view/page-size arguments override the default; structured logs
stay UTC and console defaults stay machine-local. Named timezone and scheduler
preferences are outside this display-only increment; scheduling remains disabled.

Forms carry the revision they loaded. If another tab/CLI changed the same name,
the update returns HTTP 409. Reload and review before saving again; it does not
overwrite the newer revision. The source report and software revision are retained
with each screener. Names allow 1–64 ASCII letters/numbers/spaces/underscore/dot/
hyphen, starting with a letter/number; they are case-sensitive and cannot have
leading/trailing spaces. Never enter credentials into names/search/filter values.

## CLI and setup-agent mapping

PowerShell, using already indexed report IDs:

```powershell
.\.venv\Scripts\python.exe -I -S run.py screener-list
.\.venv\Scripts\python.exe -I -S run.py screener-save --report REPORT_ID --name "My screener"
.\.venv\Scripts\python.exe -I -S run.py screener-show --revision REVISION_ID
.\.venv\Scripts\python.exe -I -S run.py screener-export --revision REVISION_ID --report REPORT_ID --destination artifacts/selected.csv
.\.venv\Scripts\python.exe -I -S run.py preferences-show
.\.venv\Scripts\python.exe -I -S run.py preferences-set --page-size 50 --display-timezone utc
```

Ubuntu/WSL/macOS use `.venv/bin/python` with the same arguments. `--demo` selects
the separate web demo workspace. User-run saved-data commands do not fetch data.
To update, supply `--expected CURRENT_REVISION_ID` printed by show/list. Omit it
only for initial creation. `preferences-set` takes both fields explicitly.
Screener save defaults to an all-row view; `--selection-file PATH` accepts the
version-1 `{ "version": 1, "selection": {...} }` payload shown in the screener's
saved definition. All selection fields are required. It is bounded to 64 KiB,
validated against the selected report, and never executed as code.

`screener-export` evaluates the chosen immutable revision on the chosen report.
The default is full-schema filtered CSV; `--format watchlist` emits the same
IV-grouped TradingView text as the web interface. Its destination must be a new
file under an existing directory; it never overwrites an existing export.
Setup agents can guide these same commands without inspecting real saved data or
credential stores. Ordinary CLI output can contain private view definitions;
agent-review summaries contain only fixed check statuses and safe codes.

## Recovery and verification

Migration 4 leaves existing artifacts/settings/history intact. Updates append a
revision and move the current pointer atomically. C5 backups retain all revisions,
current pointers and source-report dependencies; restore migrates older catalogs
through the existing reviewed migration mechanism. Old software refuses schema 4.
There is no downgrade, silent preset migration across expression versions, or
removal of unavailable fields. Current lists are bounded to 1,000 screeners and
history to the latest 100 revisions per name; older revisions remain stored and
addressable by ID. No background cache or refresh is added.

HTTP POST bodies are now bounded to 256 KiB in Flask and Waitress to carry the
bounded saved-view JSON; same-origin/CSRF/duplicate-field checks still apply. No
file upload, secret entry or arbitrary JSON execution endpoint was added.

Verified on Ubuntu/Python 3.14.4 with guarded synthetic tests: immutable revisions,
stale edits, applied-filter/export parity, invalid/unknown fields, CLI diagnostics,
web CSRF, historical application, preference overrides and recovery of revisions.
276 core and 24 web tests pass. Browser ergonomics/real saved-data acceptance remain
pending. Native Windows verification stays at major releases; macOS is unverified.
