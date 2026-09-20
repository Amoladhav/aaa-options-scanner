# Localhost saved-results preview (C3a)

A runnable personal web preview now shares the existing Python CRS/master/OTA/
Tradier composition and CSV protection. No Node build, cloud service, credential
manager or provider request is needed for its synthetic demo. This is C3a;
advanced history, editable settings and durable fetch/cancel jobs are C4–C6.
Scheduling is unavailable in this app. Starting it does not start or change any
existing scheduler. Finviz/IBKR implementation stays after C6 user acceptance.

## Install optional web dependencies once

Use the interpreter/environment verified in [SETUP.md](SETUP.md). Review
[requirements-web.txt](../requirements-web.txt) and [dependency review](WEB_DEPENDENCIES.md).
Do not overwrite an existing virtual environment or share one between operating
systems. No root/admin install is needed for Python packages.

Ubuntu/WSL or macOS Terminal, from the project root:

```bash
.venv/bin/python -I -m pip --isolated install --only-binary=:all: -r requirements-web.txt
.venv/bin/python -I run.py web --demo --port 8765
```

Native Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -I -m pip --isolated install --only-binary=:all: -r requirements-web.txt
.\.venv\Scripts\python.exe -I run.py web --demo --port 8765
```

Use `-I` without `-S` for the app: it needs the installed web packages. A missing
wheel is a stop-and-review condition; do not silently build source packages.
The standard-library demo/core tests still use `-I -S` and need no web packages.

Open **http://127.0.0.1:8765** in your browser. Use that exact host, not `localhost`,
a LAN address or a tunnel. `--port` can select an unused port from 1024–65535;
use the same port in the browser. Stop with **Ctrl+C** in the terminal. No worker
or OS startup task is installed. If the port is occupied, stop the existing server
or select another port. The app never tries a public binding as a fallback.

For WSL, first try the printed address in the Windows browser. Localhost forwarding
must work without a tunnel or LAN bind; if it does not, stop and identify the WSL
network configuration before changing it. Actual WSL-to-Windows browser forwarding
has not been verified here.

`--demo` creates/reuses a separate synthetic workspace at
`artifacts/web-demo-workspace/`. The root page lists its source IDs and reports;
open the saved **Synthetic demo** report or build a new report from its synthetic
prices and OTA. The data has historical invented dates, so age badges may read
stale; that is intentional. Tradier is not attached in the demo. Its missing quotes
are marked, not fabricated. Synthetic public-format route fixtures separately test
ATM quote rendering and partial batch failures.

## Open your selected saved results

These steps read private provider artifacts and are **user-run**. Agents inspect
only intended `artifacts/agent-review/` summaries. Do not share captures or private
report screenshots with the agent as diagnostics.

1. Stop the demo server.
2. Follow [CATALOG.md](CATALOG.md) to index the exact saved public price/master,
   OTA results and completed Tradier batch you want. No fetch occurs. The originals
   stay untouched; the catalog stores immutable copies and hashes.
3. Start the real workspace, omitting `--demo`:

```bash
.venv/bin/python -I run.py web --port 8765
```

PowerShell:

```powershell
.\.venv\Scripts\python.exe -I run.py web --port 8765
```

4. Choose the **prices**, **OTA** and **Tradier** artifact IDs and click **Build
   saved-data report**. Missing providers are permitted and explicitly shown.
   A mismatched Tradier master/profile is rejected; choose matching saved inputs.
5. Review source IDs, source timestamps, master ID and coverage. Indexed timestamps
   are separate from observation/retrieval timestamps. Human timestamps display in
   the runtime machine's local timezone with offset; source UTC is preserved.

No source is implicitly selected as "latest". Page refresh/filtering never fetches
or rebuilds a report. Each explicit build pins inputs and creates an immutable
report. Simultaneous builds receive a busy response; this bounded synchronous
saved-report operation is not a durable provider job. Large saved files may take
longer to compose. No cancellation/worker-resume claim is made at C3a.

## Browser acceptance checkpoint

After the synthetic preview, test your saved-data report yourself:

- Open sources, report and run history; refresh and restart without losing reports.
- Confirm total master members and excluded/unranked rows remain present. OTA
  screener membership must not shrink the master universe.
- Confirm attached/missing/failed Tradier counts and actual call/put bid/ask values.
  The earlier blank-quote issue is not accepted as resolved until you verify this.
- Try stocks/ETFs, search and top/bottom/both X% tails, score ordering and next page.
  Selection applies to the complete report before pagination. Tied percentiles may
  yield more/fewer rows than exactly X%. Fixed CRS labels/candidate rules stay fixed.
- Download **full CSV** and **filtered CSV**. Filtered means every selected row,
  not just the visible page. Open in Excel and verify formulas stay text and
  decimals/negative returns remain numeric; returns/percentiles use fractions.
- Inspect row field diagnostics and source metadata. Retrieval age is not proof
  of quote freshness; absent, failed, stale and unranked states stay distinct.
- Find startup/report log paths and sanitized `Agent review:` paths in the terminal.
  Logs/errors are retained. No automatic retention/deletion is configured.

Record OS, shell, browser, steps passed and safe failure descriptions. User/browser
acceptance is pending; automated route tests are not visual/Excel verification.
Native Windows/macOS and WSL browser forwarding are separately pending.

Known C3a scope: web reports share calculation/master/provider joins and full CSV
with CLI for identical inputs/settings. This preview uses the reviewed candidate
defaults, displayed and pinned in each report; it does not yet load/edit personal
CLI candidate settings. They currently use no prior-session history input, so rank-change/history
columns do not claim parity with CLI reports that attach daily history. C4 supplies
append-only/canonical history and replay; C5 supplies backup/restore; C6 supplies
settings and durable user-initiated fetch lifecycle before its acceptance gate.

## Offline checks and recovery limits

Core suite:

```bash
python3 -I -S tools/test_offline.py
```

Optional web suite uses **only** the reviewed package directories from an explicit
installation, with environment/network/process/real-database guards. Ubuntu/WSL/
macOS: replace `3.14` with your verified interpreter's major.minor version:

```bash
.venv/bin/python -I -S tools/test_web.py --deps .venv/lib/python3.14/site-packages
```

PowerShell:

```powershell
.\.venv\Scripts\python.exe -I -S tools\test_web.py --deps .venv\Lib\site-packages
```

During development, reviewed wheels were extracted to ignored
`artifacts/web-test-deps` without executing setup hooks. That alternative runner
argument is `--deps artifacts/web-test-deps`; it is not a packaged dependency copy.

Missing/changed registered files fail closed. Stop and run the user-run
`catalog-reconcile`; do not edit catalog JSON/SQL to suppress the mismatch.
C5 restore is still pending. Keep originals and catalog private; do not delete
inputs or adopt orphan files automatically. No filesystem browser, raw capture
route, entire-artifact static mount, credential entry form or provider endpoint is
available. Loopback, strict Host/Origin, CSRF, escaping and response headers are
verified controls for this preview, not authorization to expose it remotely.
