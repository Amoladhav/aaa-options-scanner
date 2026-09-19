# AAA Options Scanner

Cross-sectional momentum with a combined OTA research dashboard, session history,
configurable shortlist filters and a user-run daily workflow. Synthetic examples
need no packages or credentials. Authenticated requests remain user-run.

## First combined output

From the project root, generate the draft with invented data:

```bash
python3 -I -S run.py dashboard-demo
```

For your already saved public prices and OTA results (no request or token needed):

```bash
python3 -I -S run.py dashboard
```

Windows equivalents: `py -3.11 -I -S run.py dashboard-demo` and
`py -3.11 -I -S run.py dashboard`. Open the printed `dashboard.html` path.
The table joins CRS and OTA by normalized symbol, with search, sorting, stock/ETF
and long/short filters. It exports combined/candidate CSVs and departed symbols.
OTA does not alter CRS scores. Missing matches mean absent from the filtered
screener, not zero volume. Provider definitions remain unverified.

`dashboard` selects the newest saved files by modification time. Use
`--snapshot PATH --ota PATH` to select exact inputs. Synthetic/public profiles
cannot mix. Output includes copies of inputs and settings for reproduction.
Each profile stores one history record per price session; repeated runs replace
that session, never add streak days. Rank change is against the prior recorded
session, with gaps and newly ranked symbols labeled. First real run has no prior
history. Universe changes can also change ranks.

Edit [config/candidates.json](config/candidates.json), or pass `--filters PATH`.
Defaults retain tail rows with open interest >=10,000, options volume >=90,000
and vendor liquidity >=85. Optional earnings/mean-IV thresholds default to null
(disabled). Missing required values or stale inputs cannot match. Defaults allow
OTA retrieval age <=36 hours and price age <=4 calendar days. The price-age limit
is not proof of the latest exchange session; use a refresh for a current report.
Green rows mean numeric settings match, with metric definitions still unverified.

## One-command daily run

After public dependency setup below, with an active OTA browser session:

```bash
.venv/bin/python -I run.py daily --profile public
```

```powershell
.\.venv\Scripts\python.exe -I run.py daily --profile public
```

This refreshes prices, prompts for the current OTA token, fetches pages (100 rows
by default), then writes the combined dashboard. Each stage has standard progress
and its own log/review report. A failed stage stops the workflow; it never silently
uses yesterday's output. `--page-size` and `--max-pages` are available. Cached
`dashboard` is the no-download reuse path; daily refresh deliberately downloads
full adjusted histories to avoid incorrect incremental split/dividend merging.
This is a manual command, not an unattended login or scheduler.

## Optional local credential storage

Use your OS credential store, outside Git. Install the reviewed optional direct
pin using wheels; transitive dependencies remain unlocked:

```bash
.venv/bin/python -m pip install --only-binary=:all: -r requirements-keyring.txt
.venv/bin/python -I run.py ota-token set
.venv/bin/python -I run.py daily --profile public --use-stored-token
```

```powershell
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-keyring.txt
.\.venv\Scripts\python.exe -I run.py ota-token set
.\.venv\Scripts\python.exe -I run.py daily --profile public --use-stored-token
```

`ota-token set` takes hidden input; `ota-token delete` removes the local copy.
Storage does not extend OTA session lifetime. After expiry, sign in locally and
set the new token. Default fetch still prompts and never consults stored tokens.
The explicit native backends are Windows Credential Locker, macOS Keychain and
Linux Secret Service; there is no plaintext fallback. Linux/WSL requires an
available, unlocked Secret Service and session D-Bus; otherwise setup fails with
`TOKEN_STORE_UNAVAILABLE`. See [keyring documentation](https://keyring.readthedocs.io/en/stable/).
Native store execution remains user-validation pending.

If WSL reports `TOKEN_STORE_UNAVAILABLE`, storage failed locally; it is not a
Tradier authentication response. Missing keyring dependencies, unavailable Secret
Service/D-Bus or a locked store can cause it. The exact cause is not established
by that safe error. For the standalone probe after draft approval, bypass storage:

```bash
.venv/bin/python -I run.py tradier-probe --profile sandbox --symbol SPY --prompt-token
```

Use `production` with a production key. This prompts invisibly for this run only,
never reads/writes the OS store and requires no keyring package. It still makes
an authenticated market-data request when you run it. PowerShell uses
`.\.venv\Scripts\python.exe` with the same arguments.

Paste only the token; surrounding paste whitespace is trimmed. Empty input or
internal whitespace is rejected locally as `TRADIER_TOKEN_INVALID`, before any
provider request. No account number is needed for market quotes/options chains:
see [Tradier's chain endpoint](https://docs.tradier.com/reference/brokerage-api-markets-get-options-chains).


For your Tradier key, choose the profile matching the key and run locally:

```bash
.venv/bin/python -I run.py tradier-token set --profile production
```

```powershell
.\.venv\Scripts\python.exe -I run.py tradier-token set --profile production
```

Use `sandbox` instead for a sandbox key. Paste only into the hidden terminal prompt,
never chat, command arguments or a tracked file. Profiles have separate OS entries.
`tradier-token delete --profile production` removes the local copy; revoke at
Tradier separately if needed. After approving the draft, the standalone user-run
probe is `.venv/bin/python -I run.py tradier-probe --profile production --symbol SPY`; on Windows use `.\.venv\Scripts\python.exe`.
It is not part of `daily` or the dashboard. If New York timezone data is missing,
the probe stops with `DEPENDENCY_UNAVAILABLE`; supply `--as-of YYYY-MM-DD` using
the current New York date as an explicit portable alternative. See [source access](docs/SOURCES.md)
and [monthly ATM plan](docs/CHAIN_PLAN.md) before live testing.

## Run the demo now

From this project's root on Ubuntu/WSL or macOS:

```bash
python3 -I -S run.py demo
```

On native Windows PowerShell (Python 3.11):

```powershell
py -3.11 -I -S run.py demo
```

Open the printed `report.html` path in a browser. Filter by stocks, ETFs, sector
ETFs or long/short/neutral; search symbols/companies and click headers to sort.
Demo prices and tickers are invented. The weekday-only demo calendar is synthetic.

Each run saves `universe.csv`, `rankings.csv`, `excluded.csv`, `results.json` and
`snapshot.json` alongside the HTML report. Runs get unique directories, preserving
earlier snapshots. Public and synthetic artifacts are separated and ignored by Git.

## Standard progress and run logs

All scan commands (including dashboard, OTA and standalone probes) print progress to **stdout** by
default. Each stage announces `Currently running: ...` before work begins, then
prints completion. Price downloads update after each batch, including empty
responses. Bars show **per-stage** completion, not an estimated percentage of
total runtime or an indication that every requested symbol has valid data.

```text
INFO    [######--------------]  30% Currently running: Downloading adjusted daily prices (4/13 batches) | elapsed 12.3s
```

During a blocking download the latest stage remains displayed; there is no timed
heartbeat or guessed ETA. Every update is flushed and written on a new line,
including in IDE terminals and redirected stdout. No activation or new package
is needed for progress/logging. Existing run commands stay the same.

Each run also creates an exclusive UTF-8 JSON Lines file at
`artifacts/logs/<run_id>.jsonl`, printed at startup. Each line is a structured
event with UTC timestamp, sequence, severity (`INFO`, `WARNING`, `ERROR`), run ID,
implementation revision, command/profile, stage/event, a fixed message, completed
and total counts, percentage, elapsed seconds, safe counts and error code.
The run ID matches the output directory and `agent-review` summary.

Events are flushed immediately. Previous logs are preserved; there is no automatic
retention deletion. Warnings report exclusion counts; failures preserve the last
stage and actual progress. Ctrl+C records cancellation and returns exit code 130.
The log does not contain symbols, raw provider output, arbitrary exception text,
URLs, headers or credentials. Provider stdout/stderr remain suppressed while our
own progress remains visible. No general HTTP debug logger is enabled.

Use the same `RunProgress` component for future commands and adapters. Add fixed
stage/error codes and allowlisted numeric counts instead of logging raw messages.
After public runs, agents still read only the intended `artifacts/agent-review/`
summary; ordinary run logs remain user-facing files.

## Download public data (user-run)

This command builds the current S&P 500 membership from Wikipedia, combines it
with [11 sector ETFs and 50 starter ETFs](config/etfs.csv), and downloads daily
adjusted prices with yfinance. SPY is included among the 50. The watchlist is
**not a verified top 50 by options volume**; optionability, current fund metadata,
and liquidity still need provider validation. There are no leveraged/inverse
funds intentionally selected. The old incoming supplemental stock list is not
included in this first universe.

Membership is acquired separately from price history; yfinance does not provide
the S&P membership table here. Wikipedia is a convenient secondary source, not
the index administrator. Schema/count changes fail closed. Each downloaded
snapshot records source attribution and membership observation time; this current
universe must not be used as a historical backtest membership list.

Supported target: Python 3.11–3.14. Only the standard-library path on Ubuntu with
Python 3.14.4 has been executed so far. Direct optional dependencies are pinned
in [requirements-public.txt](requirements-public.txt); transitive versions are
not locked yet. Use a separate virtual environment for each operating system.
Installation below requests wheels only, so source-build hooks are not executed.
If a compatible wheel is missing, stop and review the package/platform instead of
removing that restriction without review.

Ubuntu/WSL (macOS uses the same Python commands):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --only-binary=:all: -r requirements-public.txt
.venv/bin/python -I run.py refresh --profile public
```

Native Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements-public.txt
.\.venv\Scripts\python.exe -I run.py refresh --profile public
```

No Yahoo account token is requested or loaded by this application. yfinance is
an unofficial public-data interface and manages anonymous session cookies. The
user runs this path; agents do not inspect those cookies or run provider calls.
Downloads can fail or return partial data. Failed downloads never become synthetic
prices. Missing symbols remain in the master list and appear in exclusions.

The downloaded snapshot is the local cache: re-running a ranking uses it without
network access. A refresh deliberately obtains a new complete snapshot, because
adjusted historical prices can change after corporate actions. Incremental cache
merging and automatic scheduling are deferred.

## Replay a saved snapshot offline

Use the exact `snapshot.json` path printed by a previous run in place of the
example path below. Replays show the original as-of date, not fresh market data.

```bash
python3 -I -S run.py cached --snapshot artifacts/runs/public/RUN_ID/snapshot.json
```

```powershell
py -3.11 -I -S run.py cached --snapshot artifacts/runs/public/RUN_ID/snapshot.json
```

## Score definition

1. Use a common completed XNYS session and adjusted closes from exactly 21, 63,
   and 126 sessions earlier: `return = latest / earlier - 1` (fractional units).
2. Within stocks and ETFs **separately**, clip each horizon's returns to its mean
   plus/minus three population standard deviations, then calculate z-scores.
3. Combine horizon z-scores with weights **0.50 / 0.25 / 0.25** and standardize
   that composite again. Higher means stronger cross-sectional momentum.
4. Equal scores share a midrank percentile. Top/bottom 10% are labeled long/short
   candidates. All-equal data is neutral. At least 20 valid members are required
   per peer group. Display ranks break ties alphabetically; scores/percentiles do not.

The sector ETF filter shows their ranks among **all ETFs**, not a new 11-member
ranking. Bond/commodity/equity ETFs share the ETF distribution in this first
version; asset-class grouping is a possible later refinement.

Prices are adjusted with yfinance `auto_adjust=True`, explicitly; no automatic
repair, volatility adjustment, or missing-price imputation is enabled. Live dates
come from `exchange_calendars` XNYS closes, including early closes and DST, with a
one-hour publication buffer. The last 127 expected session prices must all be
finite and positive. Missing endpoints/history are excluded, not shifted to an
older date. Review exclusion counts: scores are relative to the valid subset,
and extensive missing data changes that comparison universe.

Compared with the [reference](reference/README.md), exact trading-session returns
replace Finviz's calendar-period performance fields; ties are equalized, missing
history is excluded, and stock/ETF peer groups are separate. No persistence or
Conviction score is included. This implements a ranking calculation, not evidence
of profitable execution. Fees, slippage, orders and performance backtests are out
of scope; scores are not calibrated probabilities or executable quotes.

## Verification and safe diagnostics

Run from the project root on Ubuntu/WSL/macOS:

```bash
python3 -I -S tools/test_intake_scan.py
python3 -I -S tools/test_offline.py
```

Native Windows PowerShell:

```powershell
py -3.11 -I -S tools/test_intake_scan.py
py -3.11 -I -S tools/test_offline.py
```

The application test runner installs network, subprocess, environment-read and
file-read guards **before collection**. It only collects `tests/`, never INBOX
or the historical reference. All provider tests use synthetic responses. The
guards protect reviewed Python code; they are not a general hostile-code sandbox.
Do not run bare pytest: the mandatory isolation entry point is `tools/test_offline.py`.

After a user-run refresh, agents may read only the printed JSON report under
`artifacts/agent-review/`. It contains a run ID, implementation SHA-256 revision,
profile, check status, counts and allowlisted error code. It contains no symbols,
account data, raw responses, headers, cookies, or exception messages. The market
snapshot and HTML/CSV reports are for the user, not agent diagnostic intake.

`DEPENDENCY_UNAVAILABLE` means the optional packages are absent from the selected
interpreter. `CONSTITUENTS_SCHEMA_CHANGED` or `CONSTITUENTS_COUNT_INVALID` needs
parser/source review. `NO_VALID_PEER_GROUP` means too few complete price series.
`SCAN_FAILED` is a sanitized unclassified provider/input failure. Do not enable
verbose HTTP logs or share raw captures to diagnose it.
`LOG_UNAVAILABLE` indicates that a run log could not be created/written;
check local disk space and permissions. A scan does not start if log creation fails.

Offline checks passed; live checks pending. Native Windows/macOS, browser
interaction, optional dependency installation, and real provider responses remain
unverified for this new increment. Cross-platform CI is prepared but has not run; Git hooks remain unconfigured.

## Sources and next increment

- [yfinance documentation](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)
- [exchange_calendars](https://pypi.org/project/exchange_calendars/)
- [S&P 500 constituent table](https://en.wikipedia.org/wiki/List_of_S%26P_500_companies)
- [Select Sector SPDR issuer list](https://www.ssga.com/uk/en_gb/intermediary/capabilities/equities/sector-investing/select-sector-etfs)
- [Intake ledger](docs/INTAKE.md) and [project status](docs/STATUS.md)

The combined dashboard, history and candidate filters are now implemented.
Next: review the draft, validate the user-run daily workflow and standalone
Tradier probe. A verified options-volume ETF selection dataset and exact OTA
metric definitions remain pending. See [source access](docs/SOURCES.md).

## Offline options enrichment

Run `python3 -I -S run.py demo --with-options` to preview separate IV rank,
IV percentile, options volume and open interest alongside unchanged momentum ranks.
Missing data remains unknown. See [input format and OTA access checks](docs/OPTIONS.md).
This enrichment report is offline; the separate user-run OTA connection check is described below.

## Paste OTA screener criteria into configuration

Use this whenever you change filters in OTA's screener. The offline `ota-config`
tool validates a pasted **complete request-body criteria array** and produces
`config/ota-screener.json`. It changes configuration, not Python source. No account,
token, clipboard package or third-party dependency is required.

From the project directory, preview a paste in Bash/Linux/WSL:

```bash
python3 -I -S run.py ota-config
```

Paste the complete array and press Enter; no EOF or Ctrl-D is required. To validate
and save in one run, use `python3 -I -S run.py ota-config --apply` instead.

Native Windows PowerShell:

```powershell
py -3 -I -S run.py ota-config --apply
```

Paste the array and press Enter. Multiline pastes submit after the closing `]`
and Enter; brackets inside quoted values do not end input. Press Ctrl-C to cancel
an unfinished paste. For help with a pasteable example, run
`python3 -I -S run.py ota-config --help` (PowerShell: `py -3 -I -S run.py ota-config --help`).
Alternatively, save only the criteria in a UTF-8 text file under
ignored `artifacts/`, then preview and apply the same file:

```bash
python3 -I -S run.py ota-config --input artifacts/ota-criteria.txt
python3 -I -S run.py ota-config --input artifacts/ota-criteria.txt --apply
```

In PowerShell use `py -3 -I -S` in place of `python3 -I -S`.

Example accepted input (complete JSON also works):

```text
[
  {field: "optionable", valueFilter: "BOOLEAN", valueChoices: "Yes", criteria: "true"},
  {field: "last", valueFilter: "RANGE_INSIDE", valueMin: 15, valueMax: 200, criteria: "true"}
]
```

The input must contain complete objects with double-quoted strings. DevTools
abbreviations (`…` or `...`), numbered display rows (`0: {...}`), Markdown bullets,
comments, trailing commas and executable expressions are rejected. Copy only the
complete criteria array, never headers, tokens, cookies, cURL or HAR exports.

Supported filter types: `SELECT`, `SELECT_CODED`, `BOOLEAN`, `RANGE_INSIDE`,
`RANGE_OUTSIDE`, `COMPARE`. Selection values must be strings; Boolean choices are
`Yes`/`No`. Optional `criteria` flags retain their Boolean or `"true"`/`"false"`
form. Range bounds must be finite numbers in ascending order. Unknown keys,
unsupported filter types, repeated fields/keys and incomplete entries fail closed.
Limits: 200,000 input characters and 100 criteria. New provider shapes require an
explicit parser update rather than silently losing fields.

OTA range objects may also include `valueChoices` equal to `RANGE_INSIDE` or
`RANGE_OUTSIDE`; the tool preserves this optional field and checks that it matches
`valueFilter`. Paste the original payload with plain underscores (`sma_50`,
`RANGE_INSIDE`). Chat/Markdown escapes such as `sma\_50` are invalid JSON and are
rejected. The saved configuration wraps the original array in `criteria`; that
array is the future POST body, not the entire configuration object. Both `"true"`
and `"false"` criteria flags are preserved; the tool does not activate every filter.

Without `--apply`, the tool prints a preview and leaves configuration untouched.
With `--apply`, it replaces the entire criteria list atomically; it does not merge
with old filters. Invalid input leaves the existing file intact. The generated
non-secret configuration can be reviewed with `git diff -- config/ota-screener.json`
once tracked; a newly created file initially appears as untracked in `git status`.
Progress and fixed-metadata JSONL logs use the standard `artifacts/logs/` location;
pasted text and filter values are not written to those logs. Validated configuration
is intentionally shown in the local terminal preview.

This prepares the request configuration for OTA integration. **It does not yet
connect to OTA or alter momentum calculations.** The row parser also exists, but
the paginated transport is available below. Live paging and timestamps remain unverified.
README usage notes and project status are updated with each implemented feature.

## OTA: paginated screener fetch (user-run)

The owner has confirmed permission for personal scripted access. The `ota-fetch`
command sends paginated POST requests using `config/ota-screener.json` and prompts
for a token without echo. It uses standard-library HTTPS with certificate checking,
a 30-second socket timeout, no cookies, redirects, retries or proxy-environment
discovery. No dependency installation is needed. It fetches screener matches;
joining them to the momentum report remains a separate next feature.

At the owner's request, OTA requests send a fixed Chrome-style `User-Agent`
(`Chrome/153.0.0.0` on Windows) for compatibility. This does not reflect the actual
OS/browser, provide authentication, or guarantee acceptance by OTA. No browser
cookies are copied. Fixed Origin, Referer, language, client hints, fetch metadata
and priority headers match the requested browser profile. HTTP/2 pseudo-headers
are represented by the HTTPS host, POST method and request path, not copied as
literal headers into this HTTP/1.1 client. Content-Length is calculated from the
encoded payload. Accept-Encoding stays `identity` because compressed response
decoding is not implemented. These headers do not reproduce a browser's TLS stack.

1. Sign in to your own OTA account in Chrome. Open Developer Tools → Network →
   Fetch/XHR, then load your screener normally.
2. Select the successful POST to `/api/secure/screeners/criteria/results`.
   Under Request Headers, copy only the **value** of `x-auth-token` locally.
   Do not copy the header name, quotes, the whole request, cookies or a HAR export.
3. In a normal local terminal at the project root, run:

   ```bash
   python3 -I -S run.py ota-fetch --profile ota
   ```

   Native Windows PowerShell:

   ```powershell
   py -3 -I -S run.py ota-fetch --profile ota
   ```

4. Paste at the hidden prompt and press Enter. No characters should display.
   The token is used in memory and is not saved; clear it from your clipboard
   afterward. If hidden input is unavailable, the command stops. Do not redirect
   a token into stdin or pass it on the command line.
5. Give the agent only the printed `artifacts/agent-review/<run-id>.json` path.
   That report contains fixed status/error codes and counts, with no token,
   headers, response body, identifiers or symbols. The raw `results.json`
   under `artifacts/ota/` is for your local review, not agent intake.

`OTA_AUTH_REJECTED` means 401/403: the token might have expired, or the request
may require different access. Sign in normally and obtain your current token for
a deliberate retry; do not assume expiry is the cause. `OTA_RATE_LIMITED` stops
without retry. Both a bare row array and the reference adapter's `results.data`
envelope are supported. `OTA_ENVELOPE_UNSUPPORTED` means another outer structure;
share only its field names/nesting so the parser can be adjusted. Never share raw responses.
An empty first page means zero matches for this request, not the entire market.

`OTA_SCHEMA_INVALID` now concerns invalid JSON or row structure, not an unusual
metric value. Where available, a fixed diagnostic identifies the structural issue.
Authentication, response-size, symbol identity and pagination checks remain strict.
Unexpected metric types/values are retained for profiling and later interpretation.

The owner verified on 2026-09-19 that the token expires with the OTA session.
Treat it as session-bound, not a long-lived API key. Before fetching, open OTA,
sign in and copy the current token into the hidden prompt. After the session
expires, establish a new session and obtain a fresh token. On 401/403 the script
stops; it never refreshes credentials or automates login. Other access failures
can also produce 401/403, so renewal is not a guaranteed fix.

Default fetch prompts without saving. Optional OS storage, described above,
reduces pasting during an active session but cannot extend its lifetime or enable
unattended daily runs across expired sessions. Exact idle
timeouts and server-side revocation mechanics remain unverified. Python does not
guarantee secure erasure of in-memory strings.

Results retain vendor metric names and a retrieval time; the market observation
time is unknown. Pages use your selected filters. `daily` and `dashboard` join
saved OTA values to momentum rankings; unattended scheduling is not provided.
The earlier single-page
user-run check passed with 77 rows and no errors
(review report `126d95ced37a4481b0e217b61b7d89e2`). Full coverage and metric
interpretation remain unverified; the current offline suite passed 125 tests.

### Pagination and limits

The default page size is **100**, with at most **50 requests**, including the final
short-page response. Page numbers start at 1 and increase; the payload and symbol-ascending
sort remain unchanged. Fetching stops when a page has fewer rows than requested,
matching the reference adapter. For 77 matches with the default size, only one
request is made. Full pages continue to the next page.

Override limits when needed:

```bash
python3 -I -S run.py ota-fetch --profile ota --page-size 100 --max-pages 50
```

PowerShell uses `py -3 -I -S` instead of `python3 -I -S`. Allowed page sizes are
1–600; page limits are 1–100. The per-response byte limit remains 2 MB; reduce the
page size if `OTA_RESPONSE_TOO_LARGE` occurs.

Repeated symbols across pages fail with `OTA_DUPLICATE_PAGE_SYMBOL`; reaching the
limit before a short page fails with `OTA_PAGE_LIMIT`. Authentication, rate-limit
and schema failures also stop immediately. No combined data file is written unless
all requested pages finish through short-page termination. Existing run outputs
remain separate and untouched. Progress is measured against the page limit until
termination establishes the actual page count, not an estimate of market coverage.

The sanitized report uses check `ota_paginated_fetch` and counts rows published,
pages requested, pages received and symbols received before failure. The user data
file records `coverage: short_page_observed`. This is not guaranteed completeness:
the provider may cap page size or ignore page numbers; realtime membership may change
between pages. Pagination has passed offline tests; live validation of page size
and server paging behavior remains pending your next user-run report.

## Cross-platform checks

The prepared [GitHub Actions workflow](.github/workflows/offline.yml) runs guarded
synthetic tests on Ubuntu, Windows and macOS, Python 3.11 and 3.14, after a user
push. It has not run remotely yet. It installs no application dependencies and
does not use provider credentials. Local Git hooks and a transitive dependency
lock remain pending. Native OS credential stores require separate user-run checks.

### Tradier schema diagnostics

If a probe reports `TRADIER_SCHEMA_INVALID`, rerun the same user-run command
with the current code and share only its `artifacts/agent-review` report. The
report now includes the last endpoint category, HTTP status when received and
a fixed allowlist of schema paths with type names (no response values, arbitrary
provider keys, URLs, symbols or headers). Zero parsed chains does not identify
which request failed. A 200 HTTP response alone does not prove a valid schema.

The expiration request uses `expirationType=false` for the simple date list;
monthly classification still comes from option-chain `expiration_type` metadata.
The parser also accepts the structured `expirations.expiration` envelope and
rejects ambiguous envelopes. The earlier failure's exact cause remains unverified
until the updated diagnostic is returned. Curl can isolate transport issues,
but this probe's sanitized report is sufficient for schema debugging; do not
paste raw authenticated captures or headers into chat.

### Raw capture, profiles and processing

`ota-fetch` preserves bounded HTTP-200 response bodies before JSON/row validation.
It never stores the outgoing token or request/response headers. Each run has:

| File | Meaning |
| --- | --- |
| `pages/001.body.json` | Original response bytes, including whitespace/numeric spelling; may contain malformed JSON if acquisition fails. |
| `pages/001.json` | Decoded response plus page number and retrieval time, when JSON decoding succeeds. |
| `capture.json` | Collected structurally accepted rows, original values, criteria and run metadata; starts incomplete. |
| `results.json` | Raw rows published only after a short page completes acquisition. Completeness beyond this stopping rule remains unverified. |
| `field-profile.json` | Per-field observed types, missing/null/blank counts, numeric/text string counts, negative counts, finite numeric min/max. |
| `normalized.json` | Separate versioned typed/usable metrics with `parsed_values` and `field_status`; never overwrites raw data. |

Profile fields come from the immediate `values` object. Nested objects and arrays
are counted as those types and preserved intact in raw data, not recursively
flattened. Present type counts partition present rows; blank/numeric/other string
counts subdivide strings, while negative counts are subsets. Missing counts are
relative to all captured valid rows. Numeric min/max combine finite JSON numbers
and numeric strings using floating-point parsing; original response bytes remain
the authority for exact numeric spelling/precision. Profiles omit raw examples.

Negative IV, `"N/A"`, blanks, booleans, mixed types and previously unknown fields
do not abort acquisition. Version-1 processing retains signed parsed numbers,
then separately marks negative metrics unusable for existing filters. Count/code
fractions or values beyond the exact-integer limit are also marked unusable.
Blank, explicit null, missing and nonnumeric values have distinct statuses. No
value is clamped to zero, and no provider sentinel meaning is assumed. Unknown
fields remain available in raw data/profile for future processing rules.

Dashboard automatically processes completed raw snapshots and displays field
statuses. Existing legacy normalized snapshots remain readable, but original
values discarded by older versions cannot be recovered. Incomplete captures
are never selected by the default dashboard and explicit incomplete input is
rejected. Failed fetches retain earlier pages and profile those valid rows;
malformed pages remain available in original body files, outside the row profile.

Reprocess a saved capture without a token or network request (use its printed path):

```bash
python3 -I -S run.py ota-process --input artifacts/ota/RUN_ID/results.json
```

PowerShell: `py -3 -I -S run.py ota-process --input artifacts/ota/RUN_ID/results.json`.
Each replay writes a new `artifacts/ota-processing/<run-id>/` directory. An incomplete
`capture.json` can be profiled, but cannot produce a normalized completed dataset.
Raw files are user-local, ignored by Git. Share only the `agent-review` report:
it includes type/count profiles for fixed known metric names, excluding ranges,
unknown field names, samples, provider identifiers and credentials.

### Live screener test matrix (user-run)

Try a narrow screener (<100 results), a medium screener (a few hundred), and a
broad screener (>1,800), including ETFs and rows with unavailable IV. For each,
record the browser result count and observation time locally, then paste its
criteria and fetch:

```bash
python3 -I -S run.py ota-config --apply
python3 -I -S run.py ota-fetch --profile ota
```

Share each generated `agent-review` report with a label such as narrow/medium/broad
and the browser count. The agent does not run authenticated requests. Default
pages are 100 rows; exactly full final pages require another request to observe
termination. Compare counts with the same filters; realtime changes can cause
mismatches. Do not treat a short page alone as proof of complete coverage.
Existing per-run files are preserved. Applying criteria replaces the current
local screener config, so save desired settings before switching screeners.
