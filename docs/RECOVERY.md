# Catalog backup and restore (C5)

The shared `RecoveryService` backs up the local catalog database and exactly the
immutable artifact files registered in its database snapshot. CLI commands expose
backup, verification and restore. Web/setup interfaces can use the same service;
web recovery controls and cloud recovery are not implemented.

This is **catalog recovery**, not a complete machine/workspace backup. It preserves
indexed price/OTA/Tradier inputs, saved reports, CRS history, canonical selections,
master versions, catalog settings revisions, C6b named screeners/display preferences, C6c jobs/input pins/progress events
and legacy import evidence/state.
It excludes credentials, OS secret stores, environment files, INBOX, unindexed
provider captures, legacy daily originals, standalone exports, logs, scheduler
settings/jobs, throttle feedback, source code and personal files outside the
catalog. Reconnect credentials separately through user-run onboarding. Scheduling
remains disabled. Keep original private captures separately if needed for future
reprocessing; catalog backups do not replace them.

## User-run commands

Run from the project root. Use a new destination each time; existing directories
are refused, including empty ones. These commands read private data, so the user
runs them. Agents use synthetic temporary workspaces only.

PowerShell:

```powershell
.\.venv\Scripts\python.exe -I -S run.py catalog-backup --destination backups/checkpoint-01
.\.venv\Scripts\python.exe -I -S run.py catalog-backup-verify --backup backups/checkpoint-01
.\.venv\Scripts\python.exe -I -S run.py catalog-restore --backup backups/checkpoint-01 --destination restored-workspaces/drill-01
```

Ubuntu/WSL/macOS Bash:

```bash
.venv/bin/python -I -S run.py catalog-backup --destination backups/checkpoint-01
.venv/bin/python -I -S run.py catalog-backup-verify --backup backups/checkpoint-01
.venv/bin/python -I -S run.py catalog-restore --backup backups/checkpoint-01 --destination restored-workspaces/drill-01
```

`--demo` selects the separate web-demo source workspace and diagnostic location;
destination/backup paths still resolve from the invoking working directory. No
source catalog is created or upgraded by backup. A missing catalog fails safely.
Absolute private-disk destinations are also supported; do not choose an existing
workspace or a directory inside its live catalog. Symlink components are refused.

Verification checks all referenced files; restore verifies again before creating
its new workspace. A restored directory contains catalog data, not application
code or dependencies. To recover the application, install the same reviewed code
in a separate clean checkout, then, with the application stopped and no catalog in
that checkout, move the restored `artifacts/catalog` directory into its `artifacts`
directory. Do not merge with or overwrite an existing catalog. Keep the original
backup intact. Exact report replay still requires the original runtime source
revision; changed software can read old reports but must not claim exact replay.

Commands print operation progress, known file counts, output location and log,
error-log and sanitized review-report paths. Only fixed status/error codes and
aggregate counts enter agent-review files. Do not share backups, database files or
raw command data with an agent. Review summaries live in `artifacts/agent-review`.

## Consistency, validation and failure handling

Python's SQLite backup API creates a consistent database snapshot, including
committed journal/WAL data; copying only a live `.sqlite3` file is not sufficient.
The snapshot defines the artifact set. Files are immutable under the application
contract, so a concurrent report publication is either included with all its
registered files or belongs to a later backup. Missing/changed registered files
fail the operation. Unregistered/orphan files are not included or deleted.
See [Python backup API](https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup)
and [SQLite online backup](https://www.sqlite.org/backup.html).

The version-1 `backup-manifest.json` includes scope, creation time, code revision,
database schema version, database hash/size and each artifact's ID/kind/path/hash/
size. It is written last after flushed copies. Verification compares the manifest
against the database's own file list, validates migration checksums and the exact
known SQL schema, runs SQLite integrity/foreign-key checks, and hashes each file.
It never executes SQL supplied in a manifest. Hashes detect corruption, not an
attacker who can replace the complete backup; use only your own trusted backups.

Restore reserves a fresh directory, copies into `.restore-pending`, rechecks copied
bytes, applies supported migrations to that copy, then publishes the catalog and
`restore-complete.json`. The backup and source workspace remain unchanged. Schema
1–5 backups are supported; newer/unknown schemas fail. Old clients still reject a
newer restored schema. Restore never starts providers, a server or a scheduler.

Failures/cancellation return failure and retain partial directories. A backup
without its completion manifest is incomplete. A restore without its completion
marker must not be treated as completed, even if catalog publication occurred just
before a final storage failure. Preserve failed output for local investigation;
retry using a new directory. There is no automatic deletion, resume, overwrite,
retention policy, or in-place disaster recovery. A busy SQLite snapshot aborts after
30 seconds; filesystem operations still depend on OS/disk responsiveness.

## Resource and privacy limits

Files stream through 1 MiB buffers rather than loading provider payloads wholesale.
Version 1 limits are 512 MB for the database, 16 MB for the manifest, 100,000 files,
220 MB per artifact and 20 GB total artifact bytes. Oversized backups fail; these
are safety limits, not measured shared-machine capacity promises. Restoring hashes
and copies files in separate passes for verification, trading disk I/O for clear
failure detection. Ensure free space for the backup and restore drill. No recurring
job, network upload or dependency is added.

`backups/`, `restored-workspaces/`, runtime SQLite sidecars and completion manifests
are ignored by Git. Other destination names outside these directories are the
user's responsibility. A private backup still contains provider/user data. The
service excludes credential locations by its catalog-only allowlist; it is not a
secret scanner for arbitrary strings stored in provider artifacts. Keep backups
on private storage with suitable OS permissions/Windows ACLs and user-managed disk
encryption. SQLite/hash manifests do not encrypt data. Off-machine copies and
retention are explicit user choices; same-disk copies cannot recover disk loss.

Validation on Ubuntu/Python 3.14.4: 264 guarded core and 21 guarded web tests pass.
Recovery tests cover report replay, legacy pins/rollback, schema-1 migration after
restore, WAL data, concurrent publication, corruption/missing files, unsupported
schema/checksums, path redirection, destination refusal, cancellation/storage
failure, bounded snapshot time and excluded private directories. Native Windows
verification remains a major-release check; macOS and real-data restore drills are
pending. No real catalog, credential store or provider artifact was inspected by
agents during implementation.

Job states are preserved on restore; no workers restart. See [job recovery](JOBS.md#lifecycle-and-recovery) before running restored work.
