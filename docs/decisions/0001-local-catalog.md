# 0001: Add an independent local artifact catalog

C3 needs stable artifact IDs and pinned report inputs before a web source picker.
Use Python sqlite3, explicit SQL migrations and immutable private files. Preserve
the existing scheduler database; it models daily claims, not report lineage.
Combining schemas now would require a real-data migration unrelated to preview.
Do not add an ORM, hosted database or second scheduler. Start with one writer and
default rollback journaling; reevaluate measured contention before selecting WAL.

The catalog owns immutable copies of explicitly indexed saved sources so later
source-file edits cannot change a report's input. This costs local disk space but
retains byte-level lineage and supports orphan detection across file/SQL failure.
No automatic import, repair or deletion. Report generation is append-only; source
indexing is idempotent. Unknown fields stay in source files, not SQL columns.

Acceptance: temp-only migration rollback/upgrade/checksums, foreign keys,
old/new IDs, missing/changed/orphan/pending detection, source preservation,
confined path/symlink checks and safe CLI diagnostics. Backups/restore are C5.
No native Windows/macOS or real-data migration is claimed verified.
