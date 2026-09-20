# Resume checkpoint: credentials, history and local web foundations

Updated: 2026-09-20. This is the next-thread entry point. All phases below are
planned unless explicitly marked complete. Do not install, authenticate, migrate
real data or start a server merely by reading this plan.

## Start here next thread

1. Read project AGENTS.md, this file, STATUS.md and the relevant section of
   FUTURE_ENHANCEMENTS.md. Check Git status and preserve unrelated changes.
2. Latest implementation checkpoint: `ec66c33` (readable run IDs and Tradier
   attachment diagnostics); prior `1204335` adds HTML CRS tail filtering and
   `6051eef` preserves all OTA fields in combined reports. 184 offline tests passed.
3. Begin C1 below: the shared credential loader and synthetic tests. No Infisical
   SDK in the scanner; retain run.py and existing commands. Do not begin the
   database migration or cloud deployment at the same time.
4. Complete each checkpoint with focused local commits, README/status updates,
   required isolated checks, staged value-suppressing scan and explicit remaining
   live checks. User performs pushes and all credentialed operations.

Suggested next-thread prompt:

> Read docs/RESUME_PLAN.md and AGENTS.md. Resume at C1: implement the shared
> environment credential loader and tests, preserving existing OS-store/prompt
> commands and explicit provider profiles. Then prepare the Infisical onboarding
> guide. Keep provider operations user-run and scheduling disabled.

## Confirmed direction and unresolved evidence

- Priority: easy onboarding, open-source foundations, personal local use first,
  reusable services for local web and eventual hosting. No hosted CI or pushes.
- Infisical is the recommended persistent-key setup; managed hosting is the easy
  optional route, self-hosting an advanced route. Users must understand managed
  hosting stores secrets outside their workspace. No service/account chosen or
  installed yet. Core is MIT; enterprise features have separate licensing.
- Environment injection keeps Python independent of the secret manager. Keep
  existing OS-store support compatible and a hidden prompt for first use.
- OTA tokens expire with their browser session. Infisical cannot renew them.
  Scheduling remains disabled. Do not automate browser token acquisition.
- Tradier batch sanitized evidence: 564 requested, 554 received, 10 failed.
  Blank dashboard quote issue is not yet verified resolved: explicit attachment
  and a newly generated HTML file still require user confirmation. Read only
  intended agent-review summaries, never raw provider artifacts.
- CRS score/percentile, fixed 10% bias labels, configurable HTML tail selection,
  CSV and raw OTA columns exist. HTML filters do not change CSV/candidate rules.
  Interactive browser checks and strategy-performance validation remain pending.

## Storage ownership: what goes where

| Material | Location / versioning |
| --- | --- |
| Source, migrations, tests, dependency definitions, docs, decisions | Git |
| Reviewed non-secret default settings, synthetic examples, config schema | Git |
| Personal screener changes, preferences, schedule, selected runs | Local versioned settings/database; ignored |
| Explicitly selected reusable screener presets | Git only after review/sanitization; no automatic promotion |
| API keys, OTA token, Infisical login/bootstrap credentials | Secret manager / existing OS store; never Git or database |
| Raw provider snapshots, HTML/CSV exports, logs, field profiles | Ignored immutable artifact files |
| Run metadata, lineage, settings revisions, master versions, CRS history | Ignored SQLite database |
| Backups, SQLite WAL/SHM files, throttle feedback | Ignored private local storage; never Git |

Git versions the software and reproducible defaults; the database versions user
activity and derived history. A private repository is not a secret store. Check
ignore rules and tracked files before changes; ignoring a tracked file does not
remove it from Git. Do not rewrite existing Git history or move user configuration
without a reviewed migration. Provider values and private paths must not enter docs.

## Checkpoints and acceptance gates

### C0 — Roadmap and handoff (complete: documentation)

This document records decisions, ordered work and acceptance criteria. Runtime
credential integration and general history database are not implemented by it.

### C1 — Shared credential loader (next)

- Centralize provider/profile-to-variable mapping. Proposed names:
  `SCANNER_OTA_TOKEN`, `SCANNER_TRADIER_SANDBOX_TOKEN`,
  `SCANNER_TRADIER_PRODUCTION_TOKEN`. Confirm no existing public env contract first.
- Read `os.environ.get()` only inside the explicit runtime loader. No secret reads
  on import, during demos, saved reports or default test collection. Domain and
  provider logic receive credentials explicitly, not through global lookup.
- Explicit env/store/prompt sources; simple automatic local mode may try env then
  a hidden interactive prompt only when the variable is absent. Empty/malformed
  input fails. Never silently cross profiles or switch source after auth failure.
- Noninteractive/cloud/scheduled operation fails safely when unavailable. Never
  prompt from a web request. Convert getpass echo warnings to safe failures.
- Log only loaded/format-valid status, never values, fragments, hashes or lengths.
  Format validation is not provider authentication. No CLI token arguments.
- Preserve existing credential-store commands. Read only the provider key needed.

Gate: isolated tests for precedence, missing/empty/invalid values, no-TTY behavior,
profile separation, output redaction and no import-time reads. Inject synthetic
mapping/getpass dependencies; do not weaken offline environment/network guards.
Focused local commit; user-run live validation remains separate.

### C2 — Infisical onboarding (after C1)

- Add docs/SECRETS.md, link README, extend SETUP_AGENT.md/SETUP.md. Avoid replacing
  the project README with a generic app.py tutorial or creating a second app.
- Beginner path: choose OS, run demo, choose managed/self-hosted Infisical,
  install CLI, browser login, init project, store key through the user's console,
  run wrapper with explicit environment/path/profile. Keep native OS steps distinct.
- Cover macOS Homebrew, WSL Debian/Ubuntu packages, Windows Scoop or official
  binary. Verify current official URLs; Linux package hosting changed recently.
  Review installers before user execution. Do not expose machine tokens in commands.
- Separate development, sandbox and production secrets with minimum scope. Add
  a safe user-run format check with allowlisted summary; no environment dumps.
- Explain login persistence, process-env limitations, OTA renewal, revocation,
  failure recovery, keyring-less WSL and optional advanced self-hosting.
- No claim that env injection guarantees memory-only storage or zero leakage.

Gate: documented exact commands match C1, synthetic CLI tests pass, user completes
one Tradier run through Infisical. Mark actual Windows/macOS/WSL verification
individually. Infisical is optional for demo and saved-report use.

### C3 — Local database foundation and artifact catalog

Use Python sqlite3 and explicit versioned SQL migrations behind a repository
interface. SQLite suits single-workspace local operation without a server.
Keep the existing scheduling database working; inspect its schema before planning
consolidation. Do not create a competing scheduler or silently migrate it.

Initial logical tables (final SQL belongs in the implementation review):

- schema_migrations: version, applied timestamp, migration checksum.
- runs: ID, workspace/profile/provider/operation, state, UTC start/end, display
  timezone, observation cutoff, code revision, input/settings/master references.
- artifacts: ID, run ID, kind, relative path, schema version, SHA-256, size,
  availability; raw files remain authoritative, immutable and outside SQL blobs.
- run_inputs: explicit source artifact dependencies for each derived run.
- settings_revisions: allowlisted non-secret settings, content hash, predecessor.
- master_versions and master_members: immutable membership snapshots and provenance.

Publish files atomically then register committed artifacts transactionally. File
and DB writes are not one atomic transaction: detect orphan/missing artifacts and
provide reconciliation. Never report complete before required outputs are durable.
Use foreign keys, bounded busy handling and short transactions. Keep DB on local
disk, not a network/shared cloud-sync directory. One writer initially.

Gate: fresh DB, upgrade, failed migration rollback, interrupted publication,
idempotent indexing, foreign-key and path checks. Old UUID and new timestamp IDs
both work. Synthetic parity; any indexing of actual provider files is user-run.

### C4 — Append-only history and reproducible reports

- Add crs_results keyed by run ID and symbol with score, percentile, returns,
  eligibility reason, peer group, price session and calculation-version reference.
  Link provider coverage and field-profile summaries to source artifacts.
- Never overwrite a calculation run. Reprocessing creates a new run linked to
  original inputs, exact settings and methodology version. Do not rank against a
  silently changed master or treat retrieval time as quote time.
- Keep a separate canonical selection per workspace/profile/price session. A
  same-session rerun may replace this selection while retaining both histories.
  Preserve existing one-record-per-session streak semantics, not one per run.
- Label history imported from existing daily files as limited: overwritten older
  same-session revisions cannot be recovered. Do not invent missing revisions.
- User-run import preview reports aggregate counts, duplicates and unsupported
  versions. Import is idempotent, leaves originals untouched and supports rollback.
- Add shared services and CLI for history list/show, explicit source selection and
  comparison. Exact commands are to be defined, not claimed available today.

Gate: same-session reruns retained, canonical selection deterministic, gaps and
master changes visible, source replay parity, no lookahead in prior-session joins,
legacy import rerun safe. Test with synthetic fixture databases only.

### C5 — Backup, restore and Git hygiene

- Version backup manifests with DB schema/version, artifact hashes and referenced
  file list. Use SQLite backup API or a coordinated quiescent backup; copying only
  a live DB file can omit journal state. Never package secrets.
- Capture a consistent artifact set with the DB, verify checksums and test restore
  into a fresh workspace before claiming recovery. Initially no automatic deletion.
- Add ignored DB/journal/backup patterns and synthetic checks that credentials,
  real captures and runtime state are not staged. Maintain reviewed templates and
  migrations in Git. Keep local commits; hosted CI remains disabled.

Gate: restore drill, corrupted/missing artifact detection, migration-after-restore,
no secret inclusion, reviewed staged scan. OS/disk encryption and backup destination
remain user configuration; SQLite itself is not automatically encrypted.

### C6 — Local web and eventual hosting (later)

- Local web pages call the same credential, settings, history and report services.
  Add source pickers, coverage, run history, saved report controls and downloads.
  Display-only tail filters remain distinct from persisted strategy settings.
- Shared hosting requires authentication, workspace authorization and per-user
  credential references. Never mutate process-wide env for different web users.
- Environment injection remains suitable for application-owned server secrets.
  Container updates/rotation require deployment lifecycle handling; secret sync
  does not magically refresh an already running process.
- Reassess PostgreSQL and object storage when multiple hosts/concurrent writers
  require them. Preserve domain/services through storage adapters; migration and
  deployment changes still require work, not a promise of zero modifications.

Gate: local CLI/web parity and access-boundary tests before any hosted phase.
No cloud account, deployment, Redis queue or ORM is required for C1-C5.

## References checked for the design

- [Infisical license and repository](https://github.com/Infisical/infisical)
- [Infisical CLI injection](https://infisical.com/docs/cli/commands/run)
- [Infisical login storage](https://infisical.com/docs/cli/commands/login)
- [SQLite deployment guidance](https://www.sqlite.org/whentouse.html)
- [SQLite backup API](https://www.sqlite.org/backup.html)
- [ECS environment secret updates](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html)
