# Reports from a completed OTA screener fetch

Generate reports after the fetch completes. These commands read saved files and
make no provider request or credential-store access. Agents use invented examples;
the user runs reporting against real provider data.

Ubuntu/WSL/macOS, from the project root:

```bash
.venv/bin/python -I run.py ota-report
```

Native Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -I run.py ota-report
```

With no input, the command selects the most recently modified saved
`artifacts/ota/*/results.json`. It does not wait for an active fetch: until that
fetch finishes, this may be an older result. Check the printed input path,
retrieval time and row count. To report a specific completed run, use its printed
raw-data path, replacing `RUN_ID` below:

```bash
.venv/bin/python -I run.py ota-report --input artifacts/ota/RUN_ID/results.json
```

The input must be a completed raw OTA snapshot. Incomplete `capture.json`, an
individual page response, normalized data, duplicate symbols or unreadable input
stop generation. No fallback to an older result or invented data occurs after an
explicit input fails. Use `ota-process` for profiling an incomplete capture.

## Screen and files

The console shows total rows/pages, retrieval time, quality counts and a bounded
preview (20 rows by default). `--console-rows 0` prints only the summary; values
0–100 are allowed. This display limit never limits the exported dataset.

Each successful generation creates a new ignored directory under
`artifacts/ota-reports/<report-run-id>/`:

| File | Contents |
| --- | --- |
| `report.html` | Self-contained table with search, sector filter, sorting, pagination and field-quality details |
| `rows.csv` | Every row and every observed immediate `values` field; nested values encoded as JSON |
| `source.json` | Exact bytes of the saved input snapshot; not a new provider response |
| `report.json` | Shared report model with all rows, summary, field profile and source fingerprint |
| `field-profile.json` | Observed types, missing/null/blank counts and numeric ranges |
| `ota-symbols.txt` | One normalized symbol per line, covering this OTA result only |
| `manifest.json` | Completed report marker, code revision, source SHA256 and counts |

`--page-size 25`, `50`, `100` or `250` sets the initial HTML page size. The browser
also allows changes. Search/filter changes return to the first page; headers sort
columns. HTML displays a selected set of common fields. Unknown fields remain in
CSV/JSON and the field-profile panel. Browser numeric sorting is for navigation,
not a financial calculation; source display strings retain their original values.
The static page uses no CDN, analytics or remote requests. JavaScript is required
for the main interactive table; CSV/JSON remain usable independently.

The CLI prints report, CSV, JSON, field-profile, log/error-log and sanitized review
paths. Reports publish only after the complete bundle is written. A failed write
can leave a `.pending` directory; it is not a completed report, even if some files
exist. Previous outputs and the source snapshot are not overwritten. Retention is
user-managed; copying full snapshots consumes additional local disk space.

CSV is the spreadsheet export in this increment. Native XLSX styling/sheets are
not implemented. CSV prefixes potentially executable spreadsheet text with an
apostrophe, and encodes nested values as JSON. Use `source.json` for exact types:
`[missing]`, `null` and quoted blank-string cells are display conventions, and a
literal source string could contain the same text.

## Interpretation and master-list joins

This is an OTA inventory, not a new ranking system or master universe. It preserves
all captured rows, including symbols outside the master list. It does not clamp
values, remove negatives, force mixed values into numeric ranges, or invent absent
volume/price fields. The report names fields absent from every row explicitly.

Mixed-type counts mean more than one non-null JSON type was observed in a field.
Missing-cell totals cover observed fields only, not every possible provider field.
Negative and numeric-string counts describe the data, not eligibility decisions.
Retrieval time is not quote time. A short final page is not proof of full provider
coverage. Mean IV/gauge/spread-liquidity values keep their existing meanings; they
are not substituted for IV rank/percentile or Tradier ATM bid/ask spreads.

For master-driven CRS ranking and joins, use the existing saved-data dashboard:

```bash
.venv/bin/python -I run.py dashboard
```

It requires a saved public master/price snapshot and OTA results. Use explicit
`--snapshot`, `--ota` and `--tradier` paths to control which runs are joined, as
explained in README. The dashboard's long/short labels come from CRS; this new
inventory does not recreate the INBOX report's earlier scoring/strategy rules.

The combined dashboard now includes all observed OTA fields as `ota_raw.*`
columns alongside CRS score, rank, percentile and 21/63/126-session returns.
`master.csv` and `combined.csv` contain the same complete master list, including
rows lacking sufficient prices for CRS. They use an Excel-friendly UTF-8 BOM;
returns and percentile remain fractions. This does not expand the master to every
OTA symbol. Received, matched and outside-master counts explain the join.

Raw fields retain negatives, strings, nested JSON and unknown fields. `[missing]`
means an absent field, `null` an explicit null, and quoted blanks a blank string.
`[not returned]` means no matching source row; `[not captured]` identifies older
typed-only inputs. Source sector and last price never overwrite the master sector
or adjusted close. Raw columns sort as text; interpreted numeric columns sort
numerically. CSV formula protection may prefix source text with an apostrophe.
The copied `ota-input.json` preserves original source values for replay, while
`results.json` retains raw values for matched master rows. Neither CSV formatting
nor existing candidate filters changes CRS calculations.

## Synthetic preview and future web controls

```bash
.venv/bin/python -I run.py ota-report-demo --console-rows 5
```

PowerShell uses `.\.venv\Scripts\python.exe -I` instead. Demo data is clearly labeled
invented and is not written into the live OTA fetch directory.

`ota_reporting.py` owns the pure model, shared option validation and renderers.
`ota_report_service.py` owns saved-input loading, provenance and report publication.
The CLI is a thin adapter. Future web jobs should call the service using a validated
workspace artifact ID, expose source selection/preview/page size and download links,
and reuse the same row/quality model. Do not put report logic in web handlers or
read arbitrary browser-supplied filesystem paths. These web controls remain planned.

Offline tests cover 5,642-row export parity, mixed/negative/missing fields, exact
input-byte preservation, malformed/incomplete data, duplicate rows, spreadsheet
formula protection, HTML/terminal escaping, safe diagnostics and failed publication.
HTML payload/static checks passed; interactive browser behavior and real-data
report validation remain user-run and pending.
