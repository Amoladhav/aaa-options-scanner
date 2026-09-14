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
