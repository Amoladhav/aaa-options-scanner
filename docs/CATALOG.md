# Local catalog (C3)

The standard-library catalog stores metadata in
`artifacts/catalog/catalog.sqlite3` and immutable copies under
`artifacts/catalog/files/`. Keep this on a private local disk, outside shared/cloud
sync folders. The source files remain untouched. SQLite is not encryption.
No scheduler is started or migrated: `artifacts/scheduler/schedule.sqlite3` retains
its existing version-1 settings/jobs schema. No real database was opened by agents.

From the project root, Ubuntu/WSL/macOS:

```bash
.venv/bin/python -I -S run.py catalog-init
.venv/bin/python -I -S run.py catalog-index --kind prices --input artifacts/runs/public/RUN_ID/snapshot.json
.venv/bin/python -I -S run.py catalog-index --kind ota --input artifacts/ota/RUN_ID/results.json
.venv/bin/python -I -S run.py catalog-index --kind tradier --input artifacts/tradier/production/RUN_ID/batch.json
.venv/bin/python -I -S run.py catalog-reconcile
```

Replace each `RUN_ID` with your actual selected saved run; sandbox batches use the
`sandbox` directory. Native PowerShell uses `.\.venv\Scripts\python.exe` in place
of `.venv/bin/python`; the command arguments and forward-slash input paths work on
both. Index/reconcile are user-run because they read private saved provider data.
Agents test only synthetic files. No provider request occurs during indexing.

Each indexed source prints an opaque Artifact ID for the future web picker.
Only the documented saved-source layouts are accepted; no arbitrary file upload,
credential file, raw HTTP capture, INBOX or entire-artifacts static serving.
Completed/partial Tradier batches are supported; incomplete batches are rejected.
Schema checks preserve unknown OTA values in the captured source; interpretation
continues through existing typed/report services. Tradier master compatibility is
checked when composed with the selected prices, not guessed at ingestion.

Reindexing identical source kind/profile/bytes is idempotent. Hash checks fail
closed if a registered file is changed/missing. Source metadata and report input
IDs live in SQL; large payloads remain files. The index time is not the source's
observation time. Legacy and timestamp-prefixed run IDs are accepted.

SQL migrations are versioned/checksummed in `src/trading_scanner/migrations/`.
The initial schema includes runs/artifacts/input lineage, master membership and
settings revisions. Immutable report/settings inputs are supported; editing
C6b named screeners/display preferences now have their own schema-4 revision tables. Schema 2 adds [CRS history](CRS_HISTORY.md)
for new catalog reports; schema 3 adds explicit legacy import/rollback. No ORM or WAL is
needed for the initial one-writer catalog. Connections are per operation with
foreign keys, a bounded busy timeout and explicit rollback on failure. See
[Python sqlite3](https://docs.python.org/3/library/sqlite3.html).

Files are flushed before rename and registration. POSIX directory entries are
also fsynced; Windows directory durability needs a separate platform smoke check.
File publication and database registration cannot be one atomic transaction.
`catalog-reconcile` reports available/missing/changed/orphan/pending counts and
returns failure when review is needed. It never deletes or adopts unregistered
files. Stop indexing, keep both originals and catalog, and investigate locally;
[C5 backup/verify/restore](RECOVERY.md) now protects the registered catalog.
Automated reconciliation repairs remain unimplemented.
Log/error-log and allowlisted aggregate review paths use the shared progress sink.
