# 0005 — Catalog snapshot recovery with explicit scope

Date: 2026-09-21. Status: adopted for C5.

Use SQLite's backup API to snapshot the catalog, then copy exactly its registered
immutable artifacts. Publish a versioned checksummed manifest last. Restore only
to a fresh workspace, verifying bytes/schema/lineage before upgrading the copied
catalog. Keep the backup intact and fail on incomplete or changed inputs.

This implements recovery for the current saved-report/history workflow. It does
not silently broaden ownership to credentials, unindexed captures, configuration,
logs or the separate scheduler. Those remain user-managed and explicitly excluded.
Future persisted settings/jobs must define their recovery contract when added.

Rejected: raw copying of a live database (journal consistency), recursive workspace
archives (credentials/unbounded private input), in-place restore (overwrite risk),
and background backup jobs (resource/pacing/lifecycle scope). One shared service
supports CLI and future web adapters; only CLI controls are implemented now.

Tradeoffs: backup copies consume disk; restore verifies in multiple passes. Known
schema validation deliberately rejects unknown extensions rather than executing
unexpected SQL. No encryption or tamper-proof signature is provided. Exact replay
still depends on the original software revision. See [recovery](../RECOVERY.md)
for commands, limits, excluded state and verification evidence.
