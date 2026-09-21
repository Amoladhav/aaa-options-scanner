# 0004 — Append-only catalog CRS history with pinned replay inputs

Date: 2026-09-20. Status: adopted for C4a; legacy migration remains C4b.

The existing catalog retains immutable reports, but web reports lacked prior-session
ranks and standalone daily files overwrite earlier same-session revisions.

Add a CRS projection to the existing catalog, committed with report registration.
Retain every calculation and keep a separate canonical pointer keyed by profile,
price session and method. Last committed ordinary report wins deterministically;
replays preserve provenance without replacing the pointer. The prior report is an
explicit input artifact, selected only from earlier sessions of the input snapshot.
Pin evaluation time and candidate settings; reject exact replay across code changes.

Rejected: a second history database (split transactions), overwriting result rows
(lost provenance), counting every rerun as a new session (incorrect history), or
silently importing legacy files during startup (unreviewed changes and incomplete
historical evidence). Legacy daily files remain compatible until an explicit
preview/import/rollback increment can label their limitations.

Tradeoffs: report creation adds SQL writes and disk growth; the existing JSON
report remains authoritative. Reproducible replay is restricted to identical code;
current canonical selection is not historical availability. No background worker
or new dependency is needed. Schema 2 is forward-only; old clients fail closed.

Acceptance is documented in [CRS history](../CRS_HISTORY.md). C4 is not complete
until legacy import/recovery and CLI daily-history integration are verified.
