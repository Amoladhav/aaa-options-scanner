# Grouped dashboard filters (C3b)

The localhost dashboard now supports column comparisons and nested AND/OR groups.
Restart the existing server and reopen a saved report. No report rebuild, provider
request, dependency installation or database migration is needed. Standalone HTML
reports retain their earlier controls.

## Build a filter

1. Open **Column filters · AND/OR groups and column comparisons**.
2. Choose **ALL conditions (AND)** or **ANY condition (OR)** for the outer group.
3. Click **Add rule**. Choose the left column and comparison.
4. For a constant threshold or text, use **A value / presence check** and enter
   Value. Presence checks need an empty Value. Multiplier/right column are unused.
5. For `meanIvPcnt > 1.5 × ivLow1YrPcnt`, choose left `meanIvPcnt`, comparison `>`,
   **Multiplier × another column**, multiplier `1.5`, and right `ivLow1YrPcnt`.
   Value is unused in this mode. Right-column choices show the unit family.
6. Click **Add nested group** to express parentheses. For example, an outer ALL
   group can contain that column comparison and an inner ANY group containing
   `ivGauge = 1` and `ivGauge = 2`:

```text
(meanIvPcnt > 1.5 × ivLow1YrPcnt AND (ivGauge = "1" OR ivGauge = "2"))
```

7. Click **Apply filters**. The applied expression appears above the editor and
   the result returns to page 1. Search, stock/ETF selection and CRS tails also
   apply; they are outside the expression and combine with it using AND.

Add/remove and mode changes submitted with them edit a **draft**. The table and
downloads continue to use the last applied expression. Errors leave that applied
selection intact and keep a structurally valid draft available for correction.
**Discard draft** returns to the applied filter. **Clear column filters** applies
an empty outer ALL group; it preserves search, tails, sorting and visible columns.
Navigation, sorting and exports use the applied expression, so apply or discard
your draft before moving elsewhere. There is no automatic saving or background work.

## Comparison and missing-value semantics

- Constant/text rules retain C3a semantics: case-insensitive text, numeric equality
  when both operands are numeric, and separate absent/null/blank/present checks.
  Raw OTA fields read the retained original values, not display markers.
- Column comparisons are numeric only: `=`, `≠`, `>`, `≥`, `<`, `≤`. Finite numeric
  strings are accepted; booleans are not numbers. No text-to-column comparisons,
  implicit unit conversions, division, arbitrary functions or NOT groups exist.
- A comparison with an absent, null, blank, non-numeric or non-finite operand is
  false, including `≠` and multiplication by zero. An OR group can still match
  through another rule. Add an explicit presence rule to include unknown values.
- Every nested group needs at least one rule/group. Empty ANY is rejected. An
  empty outer ALL means no column restriction. Parentheses, not operator-precedence
  guessing, determine nesting. Group depth is at most four including the root.
- Multipliers are finite decimal numbers between -1,000,000 and 1,000,000, with
  at most 32 characters. Source numeric parsing has a 128-character bound and a
  four-digit exponent bound. Multiplication uses a private Decimal context with
  enough precision for these bounds; it never rewrites source values or scores.

## Unit checks

Only fields with explicitly registered compatible unit families support column
arithmetic. A numeric-looking unknown field is not proof of its financial units.
All report columns remain available for constant/text/presence filters and sorting.

| Compatible family | Examples |
| --- | --- |
| OTA IV percentage points | `meanIvPcnt`, `ivHi1YrPcnt`, `ivLow1YrPcnt`, their raw OTA counterparts |
| Return fraction | `r21`, `r63`, `r126` |
| Standardized score | `score`, `z21`, `z63`, `z126` |
| Rank position | `rank`, `rank_change` |
| Rank fraction | `percentile` |
| Quote price | adjusted close, Tradier underlying/strike/bid/ask/spread fields |
| Bid/ask spread percentage points | Tradier call/put `spread_pct` (the existing calculation multiplies by 100) |
| Option contracts | OTA option volume/OI and Tradier call/put volume/OI |
| Underlying shares | OTA average volume and Tradier underlying average volume |
| Calendar days | `daysToEarnings` and its raw OTA counterpart |

The raw OTA counterparts of the registered OTA contract/share/day fields also
share those families. Categorical `ivGauge`, opaque vendor liquidity scores,
timestamps, diagnostic objects and unverified raw fields have no arithmetic unit.
For example, `r21 > meanIvPcnt` and `percentile > r21` are rejected. A constant
return threshold of `0.10` remains 10%; no comparison silently rescales it to 10.
These unit families are a project validation contract, not verification of provider
methodology, currency conversion, aligned timestamps, comparable lookback periods,
split adjustments or quote freshness. Those provenance limits still apply.

## Shared service and versioning

`report_expressions` validates a version-1 JSON rule tree into immutable nodes.
`Selection(expression=...)` and `select_rows` use it once per selection, before
pagination. Table, filtered CSV and IV-section watchlists share the evaluator.
Full CSV stays unfiltered. Evaluation does not change candidate rules or rankings.

The envelope is `{"version":1,"root":...}`. Nodes have exact keys:

- Group: `{"type":"all"|"any","rules":[...]}`.
- Literal: `{"type":"literal","field":"score","op":"gt","value":"0"}`.
- Column: `{"type":"column","field":"meanIvPcnt","op":"gt","other":"ivLow1YrPcnt","factor":"1.5"}`.

All nodes together allow at most 32 leaves and 64 total nodes; encoded expressions
are limited to 32 KiB. Requests including applied expression, draft and controls
are limited to 128 KiB. Unknown versions/keys/columns, duplicate JSON keys, malformed
trees and oversized inputs fail validation. Text is never executed as code.

Old `field`/`op`/`value` URLs and Python `ColumnFilter` selections remain readable.
The web editor migrates them to a versioned ALL group without changing membership.
If a caller supplies old filters and an expression, both combine with AND within
the same limits. `expression_for_selection` provides that shared migration.

Web controls call the pure `edit_expression` application service; Python/CLI/setup
consumers can use the same functions and validation. Existing CLI flags are unchanged;
no separate command-line expression editor is claimed. Personal preset/revision
persistence is C6. C4 can pin these versioned rules during the planned history work;
this increment does not migrate or write historical runs.

## Verification and remaining acceptance

222 guarded core tests and 17 guarded web tests passed on Ubuntu/Python 3.14.4.
Coverage includes nested truth tables, decimal precision, absent/null/blank values,
unit rejection, bounds, legacy migration, escaping, draft/apply separation, invalid
apply recovery, and table/CSV/watchlist membership. Web tests submit the actual
rendered form controls in-process. A 600-row synthetic report works at the full
32-rule budget; this is functional evidence, not a real-workload resource benchmark.

Actual browser ergonomics, native Windows/macOS, real-data Excel/TradingView import,
quote coverage and realistic shared-machine resource measurements remain user-run.
No live HTTP/browser check, provider call, secret read or real artifact inspection
was performed for this increment. Next is builder feedback, then C4 append-only
history; C5 recovery and C6 saved settings/durable jobs remain subsequent phases.
