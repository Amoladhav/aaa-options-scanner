# AAA Options Scanner

Cross-sectional momentum first; OTA Trade enrichment is the next increment.
The offline demo works without third-party packages or credentials. Public-data
download code is prepared and tested with synthetic transports; real Yahoo and
Wikipedia access remain unverified.

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

Offline checks passed; live checks pending. Native Windows/macOS, browser
interaction, optional dependency installation, and real provider responses remain
unverified. CI and Git hooks are not configured yet.

## Sources and next increment

- [yfinance documentation](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)
- [exchange_calendars](https://pypi.org/project/exchange_calendars/)
- [S&P 500 constituent table](https://en.wikipedia.org/wiki/List_of_S%26P_500_companies)
- [Select Sector SPDR issuer list](https://www.ssga.com/uk/en_gb/intermediary/capabilities/equities/sector-investing/select-sector-etfs)
- [Intake ledger](docs/INTAKE.md) and [project status](docs/STATUS.md)

Next: verify the first public run, then add OTA enrichment through an isolated
adapter after verifying supported authentication and field definitions. Missing
OTA access will not block momentum ranking. Daily persistence, an options-volume
ETF selection dataset, and options-candidate filters follow that increment.
