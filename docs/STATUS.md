# Project status

Updated: 2026-09-13. Phase: intake and development preparation.

## Current state

The parent and project AGENTS.md files contain shared policy revision 2. Agents
may prepare code and make local commits; the user performs pushes and every
credentialed application operation. No repository or remote exists yet.

The complete incoming pattern scan has run; finding disposition and a sanitized
reference baseline remain pending. See [intake notes](INTAKE.md). No dependencies
were installed, and no incoming application code was executed.

## Required checks available now

The intake tools use Python's standard library. Their intended minimum is Python
3.11; only Python 3.14.4 in the current Linux environment has been verified so far.
These commands run only the reviewed intake-tool tests.

From the project directory on Linux/WSL:

```bash
python3 -I -S tools/test_intake_scan.py
```

From the project directory in native Windows PowerShell, with Python 3.11 installed:

```powershell
py -3.11 -I -S tools/test_intake_scan.py
```

Seven synthetic tests passed on Python 3.14.4 in the current Linux environment.
The runner disables
site initialization and installs an audit guard before importing the local scanner:
network/process operations are denied and file reads are restricted to the tool
directory, synthetic temporary tree, and interpreter installation. This is a guard
for reviewed intake tooling, not a sandbox for arbitrary incoming/native code.
Native Windows, WSL-specific, and macOS verification remain pending.

No application offline suite, hooks, CI, or sanitized provider-run diagnostic
reporter exists yet. Do not run incoming pytest collection as a bootstrap check.
Documentation-only edits require Markdown/link/policy review and a staged secret
scan before committing; they do not require application execution.

## Findings to address before application execution

- Several entry points infer live mode from token presence. In particular,
  `run_momentum_scan.py` can select OTA from an available token even when
  `--sample` selected fixture data for Finviz. Explicit offline mode must control
  every adapter and avoid credential loading entirely.
- `run_demo.py` calls `load_secrets()` despite being a demo. Configuration resolution
  can select a local config directory, and permission checks currently warn rather
  than fail closed. Secure storage and native Windows handling need implementation.
- `diagnose_finviz.py` prints raw response snippets and exception text. Replace
  this with allowlisted diagnostic summaries before requesting user-run checks.
- The incoming capture guide requests authenticated cURL/response exports and
  token-driven mode switching. Replace it with synthetic schemas and a verified,
  authorized authentication method before implementing user-run live setup.
- The OTA mapping conflates differently named IV metrics. Missing option volume
  is replaced by a large value, and absent bid/ask spread defaults to zero, which
  can permit liquidity checks to pass. Keep unknown inputs explicit and review
  metric semantics before adopting these calculations.
- The momentum design document describes session-based persistence, while the
  configuration defaults to observation-based streaks. Specify the behavior and
  verify it on deterministic session fixtures before calling it validated.
- Requirements are unpinned, bundled dependencies are preferred only after installed
  packages, and some documentation references absent setup scripts. Establish one
  reproducible environment and accurate setup instructions.

## First development acceptance criteria

After preparing the sanitized baseline, implement an explicit offline mode with
synthetic inputs, no credential reads or provider calls, and separate output/history.
Establish and verify application test isolation before running accepted code.
Preserve reviewed strategy behavior in later increments; obtain clarification for
consequential unresolved strategy or provider-field definitions. No predictive
performance or live compatibility claims are supported at this stage.
