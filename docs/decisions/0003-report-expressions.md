# 0003: Versioned typed report expressions before history

Date: 2026-09-20. Status: implemented; browser acceptance pending.

The user requested comparisons such as `A > 1.5 * B` and AND/OR combinations after
C3a's column filters/watchlist exports, then approved proceeding with C3b. C4
history will need reproducible filter provenance, so define the expression
contract now; keep preset persistence in C6.

Use a bounded version-1 JSON tree, immutable validated nodes, registered unit
families and a single pure evaluator for full-dataset table/CSV/watchlist selection.
Literal nodes reuse C3a comparisons; old AND-only selections migrate losslessly.
Column nodes compare finite decimals with a bounded scalar multiplier and require
matching documented unit families. Missing operands produce false; NOT, division,
unit conversions and arbitrary functions are outside this increment.

Use a server-rendered nested editor with distinct draft and applied state. Add or
remove controls only change the draft; Apply validates before changing selection.
This works with the existing no-script content policy and needs no frontend build,
dependency, background work, database schema change or new credential boundary.
Pure editor functions are reusable by Python/CLI/setup consumers. Existing CLI
flags remain compatible; dedicated CLI editor/preset commands are not implemented.

Rejected: executable expression strings (`eval`), a second browser calculation
engine, inferred units from numeric-looking values, automatic conversions between
provider metrics, and persistence before the planned settings/history ownership.
The tradeoff is a page round trip for add/remove and a finite allowlist for column
arithmetic. Unregistered columns retain literal/text/presence filters and sorting.

Tests cover semantics, migration, validation and rendered-form/export parity.
The 600-row/32-rule check is functional evidence, not a resource benchmark. Actual
browser ergonomics and real-data import/freshness/resource acceptance remain open.
