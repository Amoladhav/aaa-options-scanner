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
network configuration before changing it. The user confirmed the synthetic report is visible in Windows Chrome after
following the WSL startup guidance (2026-09-20). Other network configurations
remain unverified.

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

## Column filters, sorting and TradingView export

Restart your existing server after updating the code, then reopen a saved report.
Reports do not need rebuilding for these view controls. This feature is in the
localhost dashboard; legacy standalone HTML reports keep their existing controls.

- Open **Column filters · AND/OR groups and column comparisons**, add a rule,
  choose a column/comparison/value, and click **Apply filters**. Groups can match
  ALL (AND) or ANY (OR), including nested groups. Column mode compares a left
  column with a multiplier times another column of compatible documented units.
  Add/remove edits a draft; results/exports retain the applied filter until Apply.
  See the [grouped-filter walkthrough and semantics](FILTER_EXPRESSIONS.md).
- Every saved report field is available, including raw OTA columns, quote fields,
  statuses and diagnostics. Numeric comparisons accept finite numeric strings;
  booleans do not count as numbers. Text comparisons ignore case. Equality compares
  numeric values when both operands parse numerically, otherwise displayed text.
- Absent fields and explicit nulls fail ordinary comparisons, including not-equal.
  Separate **Field absent**, **Explicit null**, **Blank text**, and **Has a value**
  checks take an empty value box. Raw OTA checks use retained originals rather
  than display markers. Structured values support text matching on compact JSON;
  nested-key arithmetic is not implemented.
- Numeric comparisons use saved units: returns/percentiles are fractions, so
  `0.10` means 10%; OTA percentage fields retain provider units. View filters do
  not change strategy thresholds, scores, source artifacts or master membership.
- Sort any field from **Sort**, or click a visible column heading to reverse its
  order. Numeric values (including numeric strings) sort first, then text; absent,
  null and blank values remain last in either direction. Ties use symbol order.
- **Visible columns** controls the table only. An empty selection restores the
  default columns. Filters and sorting can use hidden columns. CSV retains its
  full schema. Applying controls or changing sort resets pagination to page 1.
- **TradingView watchlist** exports every matching symbol across all pages, grouped
  by the saved `ivGauge`: 1 becomes `###IV1`, 2 becomes `###IV2`, and so on. Gauge
  numbers sort ascending (including IV0 if supplied); unavailable/invalid values
  go under `###IV_UNKNOWN`. Within a section, the selected sort order is retained.
  Symbols are deduplicated; no matches produces an empty UTF-8 `.txt` file.

Synthetic example:

```text
###IV1,AAA,CCC,###IV2,BBB,###IV_UNKNOWN,DDD
```

This uses the requested section syntax. [TradingView's import guide](https://www.tradingview.com/support/solutions/43000487233-how-to-import-or-export-a-watchlist/)
specifies comma-separated, exchange-prefixed symbols in a `.txt` file. Current
reports do not provide a verified TradingView exchange mapping, so this export
preserves saved symbols without guessing prefixes or changing share-class spelling.
Review symbol resolution during import; real TradingView import/section behavior
remains user-validation pending. Missing gauge is not an inferred IV category.

Cross-column comparisons such as `A > 1.5 * B` and nested AND/OR groups are now
implemented at **C3b**. Saved personal screener revisions follow in C6. Applied
filters travel in local page URLs; there is no saved preset or automatic
application to another report. Browser acceptance of the new editor is pending.

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
- Try nested AND/OR rules and a compatible column comparison; confirm draft
  changes do not affect results before Apply, and an invalid rule preserves the
  applied selection. Sort raw/quote/status columns in both directions,
  hide/show columns, move between pages and reset. Confirm missing values stay last.
- Export the **TradingView watchlist** with a filter spanning multiple pages;
  confirm IV sections, symbol resolution and membership against the filtered CSV.
- Download **full CSV** and **filtered CSV**. Filtered means every selected row,
  not just the visible page. Open in Excel and verify formulas stay text and
  decimals/negative returns remain numeric; returns/percentiles use fractions.
- Inspect row field diagnostics and source metadata. Retrieval age is not proof
  of quote freshness; absent, failed, stale and unranked states stay distinct.
- Find startup/report log paths and sanitized `Agent review:` paths in the terminal.
  Logs/errors are retained. No automatic retention/deletion is configured.

Native Windows/Python 3.11: user confirmed 224 core tests (one expected symlink
skip), 19 web tests, PowerShell startup, browser visibility and positive dashboard
feedback before C4a. Actual saved quotes, Excel/TradingView imports, realistic
resources and macOS remain unverified. C4a/C4b native Windows verification is
deferred to major-release acceptance; it does not gate C5.

New reports now use canonical prior-session CRS history and retain a link to the
exact prior report. They flag changed master membership and replayed evaluation
time. Older reports remain readable. See [CRS history](CRS_HISTORY.md) for migration,
CLI parity and replay limits. C4b now shares this history with standalone daily
reports and labels imported legacy provenance; import controls are CLI-only.
[C5 catalog recovery](RECOVERY.md) now provides CLI backup/verify/restore; web
recovery controls remain unimplemented. C6 adds saved preferences and durable jobs.

## Offline checks and recovery limits

The offline web test runner substitutes Click's native console adapter with its
ordinary-stream fallback; DLL access remains blocked. These in-process tests do
not verify Windows console I/O. Verify that separately with the demo above.

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
[C5 catalog recovery](RECOVERY.md) is available through CLI. Keep originals and
catalog private; do not delete
inputs or adopt orphan files automatically. No filesystem browser, raw capture
route, entire-artifact static mount, credential entry form or provider endpoint is
available. Loopback, strict Host/Origin, CSRF, escaping and response headers are
verified controls for this preview, not authorization to expose it remotely.

## Resource use and shared-machine constraint

Design for shared machines with 8–16 GB installed RAM running TradingView, TOS and
other demanding applications simultaneously. The owner's 32 GB machine is
development headroom, not the minimum requirement or a reason to increase resource
use. This is a design target; acceptance on 8 GB and 16 GB machines is pending.
Keep this app small and demand-driven; measure meaningful new features before
adding background work or parallel report processing. No machine-wide WSL limits
were changed.

Current implementation: one Python server process using Flask/Jinja/Waitress,
ordinary HTML/CSS, four request threads and an embedded SQLite metadata file.
There is no Node/frontend build pipeline, JavaScript polling, automatic refresh,
provider fetching or active scheduler in the web app. Waiting threads do not mean
four CPU cores are continuously busy. Waitress waits for network events; see its
[design documentation](https://docs.pylonsproject.org/projects/waitress/en/stable/design.html).

A bounded synthetic check on WSL2/Python 3.14.4 (2026-09-20) used the same guarded
in-process web boundary and a fresh process per workload. Each fixture contained
150 price sessions and synthetic OTA metrics. Single-sample observations:

| Synthetic master size | Report build elapsed / CPU | First page elapsed | Peak process RSS |
| --- | --- | --- | --- |
| 60 symbols | 29 / 18 ms | 14 ms | 45.8 MiB |
| 600 symbols | 85 / 72 ms | 20 ms | 58.1 MiB |

For 600 symbols, next-page/filter/export elapsed times were approximately
12/10/17 ms. The default page contained 25 rows and about 86 KiB of HTML. Peak RSS
includes fixture construction and the in-process test client; it excludes Windows
Chrome, the overall WSL VM, other processes and a live HTTP server's socket/thread
overhead. This is an indicative local measurement, not a resource cap, benchmark
of real provider payloads or guarantee under other concurrent workloads. No real
provider file, running user process or credential was inspected for this check.

Current limitation: pagination reduces browser rows, but each request still reads
and decodes the full immutable report before filtering; CSV is built in memory.
Large raw field sets and concurrent tab requests can therefore increase peak
usage. Four request threads are not a memory/CPU quota. Generating one report is
serialized, while page/export requests are not. Keep the default 25-row view and
measure real-data usage during user-run acceptance before selecting additional
caching, lazy diagnostics, streaming exports or other bounded optimizations.
Installed RAM is not available RAM. A measured resource budget for realistic saved
inputs is still pending. Acceptance should distinguish Python process usage,
Chrome tab usage and WSL overhead where applicable, and check responsiveness of
the user's other applications during report generation and export. Keep provider
operations user-run and scheduling disabled throughout this acceptance work.
