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
