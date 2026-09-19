# Validation record — 2026-09-13

Environment: Ubuntu / Python 3.14.4. No optional packages installed, no incoming
application code or provider requests executed by the agent.

- `python3 -I -S tools/test_intake_scan.py`: 7 synthetic tests passed.
- `python3 -I -S tools/test_offline.py`: 28 guarded unit/integration tests passed.
- `python3 -I -S run.py demo`: generated 60 ranked synthetic symbols, no exclusions,
  an HTML report, CSV exports and a cached snapshot. Browser interaction unverified.
- Development staged-change scan: 18 changed/new files, zero candidate findings.
- `git diff --cached --check`: passed. Local Markdown links and shared-policy copy
  consistency reviewed.

The later full-index scan initially stopped at two candidate matches in the
already tracked intake scanner tests. The shell continued to the development
commit (`dd8d684`) despite that check failure. This sequencing mistake is recorded
here rather than rewriting Git history. The complete full-index scan subsequently
finished: 28 files scanned, both matches confined to synthetic fixtures in
`tools/test_intake_scan.py`. AST review established their synthetic construction
without displaying matched values. [Hash-bound exceptions](scan-exceptions.json)
record exact path, file hash, line, rule and disposition; any file change requires
fresh review. This follow-up documentation commit is checked in a separate command
before the commit command is issued.

The pattern scanner is a review aid, not proof of absence of credentials. No real
credential was established by these two findings. Raw INBOX remains excluded;
its separate unresolved findings are recorded in [the intake ledger](INTAKE.md).

Offline checks passed; live checks pending. Optional dependency installation,
real Yahoo/Wikipedia schemas, native Windows/macOS and browser interaction are
not yet verified. No performance or trading-access claims are supported.

## Standard progress/logging increment

On the same Ubuntu / Python 3.14.4 environment:

- `python3 -I -S tools/test_offline.py`: 37 guarded tests passed, including stdout
  visibility while provider output is suppressed, immediate JSONL flushing,
  event schema and run-ID correlation, partial/empty download batches, profile
  resolution, exclusion warnings, failures, cancellation, log-write failures and
  protection of earlier log files. Tests reject arbitrary event metadata and
  verify that synthetic sensitive strings do not enter stdout or logs.
- `python3 -I -S tools/test_intake_scan.py`: all 7 tests passed.
- `python3 -I -S run.py demo`: displayed start/progress/completion on stdout;
  generated 60 ranked synthetic symbols with no exclusions and a per-run log.
- `artifacts/logs/` is ignored. Public requests remain user-run and were not
  executed for this increment; the existing offline isolation guard is unchanged.

Progress is measured per stage/batch; it is not a runtime estimate or evidence
that all provider data arrived. There is no periodic heartbeat during a blocking
request. The shared component and required usage for future commands are recorded
in the project instructions and README. Full staged-index scanning and exact diff
review precede the local commit; existing hash-bound synthetic exceptions apply.

## Offline options enrichment: 2026-09-18

On Linux / Python 3.14.4, `python3 -I -S tools/test_offline.py` passed 45 guarded
tests. Eight new tests cover unchanged rankings, missing/partial coverage, distinct
IV fields, stale/future withholding, zero values, invalid schemas/units/duplicates,
profile separation, safe failure, progress and deterministic demo/cached replay.
No new third-party dependency, network call or credential access was introduced.
Browser rendering, Windows/macOS and live OTA behavior remain unverified.

The incoming reference was rescanned with the reviewed value-suppressing tool:
435 filesystem files, 599 archive members, 40 findings, zero coverage gaps. Only
redacted reference views were inspected; no additional source was imported or run.
This implementation does not copy its internal endpoint/authentication flow or
its metric aliases and missing-liquidity substitutions. A supported OTA method
and metric definitions remain pending. Offline checks passed; live checks pending.

## OTA row parser

`python3 -I -S tools/test_offline.py`: 52 tests passed on Linux / Python 3.14.4.
Seven new synthetic tests cover vendor field preservation, dropped unknown fields,
missing/null/zero values, IV above 100%, invalid numeric types and nonfinite values,
duplicate normalized symbols, unsupported envelopes and empty pages. No provider
response values were copied into fixtures. No network or credential operations
were performed. The parser is a foundation, not a working live OTA integration.

## Screener paste-to-config tool

`python3 -I -S tools/test_offline.py`: 58 tests passed on Linux / Python 3.14.4.
Six new tests cover JSON/DevTools key syntax, all six supported filters, preserving
values and flags, rejecting abbreviated/executable/invalid inputs and duplicate
keys, bounded input, preview versus apply, failed update preservation, file input,
atomic replacement failure cleanup and absence of pasted values in run logs.
The guard was reviewed before collection; no network, credentials or incoming
code was used. Native Windows/macOS terminal behavior is documented but unverified.

Payload compatibility correction: OTA range criteria can contain an optional
`valueChoices` repeating the range operator. This field is now preserved and
checked for consistency. Two regression tests cover both range operators,
conflicting operators and rejecting chat-only underscore escapes without changing
input semantics. `python3 -I -S tools/test_offline.py`: 60 tests passed.

Paste usability correction: complete single-line or multiline arrays now submit
on Enter without EOF. A synthetic open-terminal test fails if the reader asks
for more input after the final newline. Tests also cover escaped strings/brackets,
input limits, incomplete input at EOF, and help examples. The guarded offline
suite passed 63 tests; native Windows terminal interaction remains unverified.

## User-run OTA single-page transport

`python3 -I -S tools/test_offline.py`: 69 tests passed. Six new tests verify the
fixed host/path, exact POST body and headers, request timeout, connection closure,
no redirect/retry or error-body reads, 401/403/429 handling, bounded responses,
unsupported envelopes, hidden-prompt fail-closed behavior, invalid-token rejection,
safe network errors and sanitized success/failure artifacts. Transport and token
input were replaced with synthetic fixtures inside the existing offline guard.
No real token was read and no authenticated request was made. The owner confirms
permission, but real token-only access and response shape remain user-run checks.

Browser-style User-Agent increment: the existing request-contract test now checks
the exact owner-requested Chrome-style header and the complete header allowlist.
`python3 -I -S tools/test_offline.py`: 69 tests passed. No authenticated request
was executed; whether the header improves OTA compatibility remains unverified.

Browser-header compatibility update: Chrome version 153, Accept, language, Origin,
Referer, client hints, fetch metadata and priority are sent as fixed non-secret
headers. The request test checks the complete header allowlist, excluding cookies,
captured Content-Length and HTTP/2 pseudo-headers; compression remains identity.
All 69 guarded offline tests passed. No captured credential values were stored or
used, and no authenticated request was made. Live compatibility remains pending.

## OTA response envelope regression

Two user-run allowlisted diagnostics reported `OTA_ENVELOPE_UNSUPPORTED`, which
occurs after HTTP 200 and JSON decoding. The previously scanned redacted reference
configuration identifies `results.data` as the row path. The transport now accepts
that exact envelope as well as legacy bare arrays, without guessing other lists.
Two synthetic regressions cover transport parsing, discarded metadata, empty rows
and malformed/unknown containers. All 71 guarded offline tests passed. No raw
user response was inspected or authenticated request rerun. A successful live
row parse remains pending the user's retry; cURL HTTP success alone does not prove it.

## OTA schema diagnostics

The user reported OTA_SCHEMA_INVALID after the envelope correction. The exact
cause is not yet established. A fixed field/reason vocabulary now distinguishes
JSON decoding, row shape/count, symbols, numeric types, negatives and nonfinite
values without emitting response values. Two new tests cover vocabulary rejection
and the sanitized CLI failure report. All 73 offline tests passed. Validation
semantics remain unchanged; live diagnosis awaits the user's next report.

Numeric compatibility increment: decimal strings and integral decimals are now
accepted using Decimal validation before conversion. Unlike the incoming adapter,
fractional counts are never truncated, and missing volume is never fabricated.
Regression coverage includes precision-sensitive fractions, huge exponents,
booleans, placeholders and nonfinite strings. All 75 offline tests passed.
No newer field-level live diagnostic was present, so this addresses a known
compatibility gap without claiming it is the confirmed cause of the user's failure.

## Verified user-run OTA checkpoint: 2026-09-19

Reviewed only the allowlisted report `126d95ced37a4481b0e217b61b7d89e2`:
profile `ota`, check `ota_single_page_fetch` passed, 77 rows, error_code null.
Reported source revision hash:
`9df30e8fab560f7d27e396e5ca09048c94735ba0fc1e93fb8ff75aa35858575d`.
This evidences one successful user-run request and row parse, not complete
pagination, metric semantics, session longevity or repeat-run reliability.
No tokens, raw response files or request logs were inspected. Earlier pending
live notes above describe their respective historical increments.

## Session lifetime checkpoint: 2026-09-19

The owner reports having verified that the OTA token expires with the session;
a fresh token must be obtained after establishing a new active session. This is
user-observed evidence, not an agent-executed expiry experiment or provider-defined
timeout guarantee. The current hidden prompt and 401/403 stop behavior remain
unchanged. No token persistence, automatic renewal/login or unattended daily
execution is implemented. Local storage would not extend session validity.

This checkpoint changes documentation only. Markdown links, policy consistency,
the staged diff and value-suppressing staged scan were reviewed. Application
tests were not rerun; the latest executed offline suite passed 75 tests.

## OTA pagination: 2026-09-19

All 80 guarded offline tests passed. Five new tests cover short/capped pages,
full pages followed by an empty page, empty first pages, page numbering and default
600-row requests, parsing 600 unique symbols, invalid bounds, repeated symbols,
page-limit failure, session expiry mid-run and no partial artifact publication.
The existing CLI test now checks combined results.json output. No authenticated
requests were executed. Default limits are 600 rows and 50 pages; termination
requires an empty page, not merely a short response. Realtime membership can shift,
so observed exhaustion is not a point-in-time completeness guarantee. User-run
validation of the new pagination behavior remains pending.

## Short-page termination correction

User diagnostic `4cacfbf5acbe46648d4560cc6a16dc81` reported two received pages,
77 symbols from the first, and `OTA_DUPLICATE_PAGE_SYMBOL` on the second. The
empty-page probe was inappropriate for that response behavior. Paging now stops
on fewer rows than requested, matching the reference adapter; full-page duplicate
and page-limit guards remain. A 77-row synthetic regression proves there is no
second request with the 600-row default. Existing pagination tests still exercise
full pages, limits and mid-run expiry. All 81 offline tests passed. Coverage is
labeled `short_page_observed`, not guaranteed complete: server caps, ignored page
numbers and realtime membership changes remain unresolved. Live retry is user-run.

## 2026-09-19 combined dashboard and isolated chain probe

- Ubuntu / Python 3.14.4: 108 guarded offline application tests passed; seven
  intake scanner synthetic tests passed. No provider request, OS keyring access,
  or optional package installation was performed by agents.
- Synthetic combined dashboard generated: 60 ranked, 48 OTA matches, nine tail
  rows matching settings. New tests cover joins, missing/stale inputs, same-session
  history replacement/gaps, escaped display, daily failure behavior, credential
  profile separation, monthly/ATM selection and Tradier transport/privacy.
- Source inventory reviewed in parallel by explicit user request. INBOX scan
  covered 435 files and 599 archive entries, 40 findings, zero coverage gaps;
  only redacted application material was inspected. No incoming code executed.
- Standalone Tradier probe is prepared, not integrated into dashboard/daily.
  Live enhanced-expiration schema, quote times, native OS keyring and Windows/macOS
  execution remain pending user validation after draft approval.
- Prepared CI matrix has not run remotely. Browser interaction remains unverified.
  No strategy performance claim; cached price-age checks are calendar-day limits,
  not a verified latest-session calendar check.
