# Project status

Updated: 2026-09-18. Phase: momentum scanner with offline options enrichment.

## Implemented

- Independent Git repository with origin; no agent pushes or authenticated calls.
  User setup commits `89dd8c8` and `cd9567b` are preserved. Initial scanned
  momentum reference commit: `cba570f`.
- Narrow reference baseline: three accepted files, 432 excluded. Full path/hash
  manifest and value-suppressing finding disposition are recorded. Raw INBOX is
  unchanged; excluded material remains unapproved. Redistribution rights unresolved.
- Pure standard-library momentum core: 21/63/126-session adjusted returns,
  50/25/25 weights, three-sigma clipping, stock/ETF peer groups, tied midranks,
  finite-price validation, missing/stale exclusions and minimum group size 20.
- Explicit synthetic demo, cached replay, sortable/filterable HTML, full master
  universe CSV, ranking/exclusion CSVs, immutable per-run JSON snapshots and hashes.
- User-run public adapter: Wikipedia current S&P membership; 11 sector ETFs and
  50 starter ETFs including SPY; yfinance adjusted daily prices; XNYS completed
  sessions with one-hour close buffer. No real provider execution by an agent.
- Allowlisted agent-review summaries and sanitized failures; no synthetic fallback
  on public-data failure. Third-party provider output is discarded, not captured.
- Standard stdout stage messages and per-stage bars for every scan command; public
  downloads report completed batches. Structured per-run JSONL logs are flushed
  at each event, with safe timings/counts, failures, warnings and Ctrl+C cancellation.

## Verification

On Ubuntu, Python 3.14.4: seven intake-tool tests and 75 offline application tests
passed. The offline runner denies network, subprocesses, real environment reads,
and files outside reviewed source/tests/config, stdlib and a synthetic temp tree.
Guards are installed before test discovery. Tests cover numeric reference parity
on complete untied inputs, ties, weights, endpoints, missing/nonfinite prices,
future-data exclusion, split-adjusted constant prices, session close buffers,
holiday/weekend schedules, group separation, provider batch orchestration with
synthetic responses, HTML/CSV escaping and diagnostic allowlists.
Progress/logging tests verify stdout visibility during provider suppression,
immediate flushing, schemas, empty batches, safe failures, cancellations,
exclusion warnings, cached profile resolution and preservation of earlier logs.

Commands from project root:

```bash
python3 -I -S tools/test_intake_scan.py
python3 -I -S tools/test_offline.py
python3 -I -S run.py demo
```

See [README](../README.md) for native Windows and user-run public setup commands.
See [validation record](VALIDATION.md) for scan disposition and commit sequencing.
No incoming application code was executed. The new active implementation is the
only runtime source; reference tests are never collected. No third-party packages
have been installed by the agent. Direct dependency pins are documented; a full
transitive lock and installation verification remain pending.

Offline checks passed; live checks pending. Tests do not prove real provider
access or strategy performance. Native Windows/macOS, browser interaction, CI,
hooks, and WSL-specific checks remain pending.

## Decisions and limits

- User confirmed cross-sectional momentum, not strength relative to SPY.
- Exact 21/63/126-session horizons replace Finviz performance period fields.
- Missing values are excluded rather than imputed; ties receive equal percentiles.
  Scores compare valid members only; exclusions can change the comparison universe.
- Stock and ETF rankings are separate. Sector ETF view is a filtered ETF ranking.
- The 50-ETF selection is a configurable starter watchlist, not verified current
  options-volume leaders. Current symbol/fund and options liquidity checks pending.
- Current membership snapshots are not historical universes for backtesting.
- Current snapshot acquisition gets a full history each refresh; cached replay is
  offline. Incremental download merging is deferred to avoid stale adjustments.
- Offline options enrichment supports separate supplied IV metrics, volume and open
  interest, synthetic examples, CSV/HTML output and deterministic snapshot replay.
  No verified live OTA access, persistence/Conviction, order execution or performance claims.
- OTA row parsing is tested with invented fixtures. Vendor fields remain separate
  from normalized IV metrics. Single-page transport uses the saved request shape;
  pagination, timestamps and live validation remain pending; see [options notes](OPTIONS.md).
- `ota-config` accepts complete pasted criteria, previews a versioned config and
  atomically replaces `config/ota-screener.json` with `--apply`. It uses shared
  progress/logging and never executes pasted code or makes provider requests.

## Next sequence

The owner has confirmed permission for personal scripted OTA access. `ota-fetch
--profile ota` now performs a user-run single-page connection test with hidden
token input, fixed-host HTTPS and sanitized diagnostics. Live execution is pending;
pagination and integration into the momentum report are not yet implemented.

1. User installs optional wheel dependencies and runs public refresh; inspect only
   the allowlisted agent-review report. Fix real schema/packaging issues if evidenced.
2. Verify an authorized OTA access method and exact IV/liquidity definitions before
   enabling its isolated adapter. Offline tests use synthetic responses.
3. Add session-based history/rotation, then options shortlist filters with unknown
   inputs explicit. Research a verifiable options-volume ETF universe separately.
