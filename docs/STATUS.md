# Project status

Updated: 2026-09-19. Phase: combined CRS/OTA dashboard and standalone Tradier probe prepared.

OTA live checkpoint: the user's short-page run returned 77 rows after one page
with no error (`ec8d6c0cf18743e38ef32fa4f0832993`). This proves the observed
single-page result, not complete coverage or multi-page production behavior.
No authenticated request was executed by agents.

The token expires with the OTA session. Default fetch prompts each time; optional
native OS storage can save the current token but cannot extend its lifetime.
Daily runs are explicitly user-started; no login automation or scheduler exists.

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

On Ubuntu, Python 3.14.4: seven intake-tool tests passed at the prior checkpoint. The current guarded
application-suite result is recorded in VALIDATION.md. The offline runner denies network, subprocesses, real environment reads,
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
access or strategy performance. Native Windows/macOS, browser interaction, remote CI execution,
hooks, and WSL-specific checks remain pending. A cross-platform offline CI
workflow is prepared, not remotely verified.

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
  Single-page live OTA access is verified. Session rank history is implemented; no Conviction score, order
  execution or performance claims.
- OTA row parsing is tested with invented fixtures. Vendor fields remain separate
  from normalized IV metrics. Pagination defaults to 100 rows, up to 50 pages,
  and stops on a short page. Duplicates, page limits and mid-run failures
  retain incomplete raw captures without publishing completed results. Live paging, timestamps and repeat-run validation remain pending.
- `ota-config` accepts complete pasted criteria, previews a versioned config and
  atomically replaces `config/ota-screener.json` with `--apply`. It uses shared
  progress/logging and never executes pasted code or makes provider requests.

## Current increment

- Combined cached CRS/OTA HTML and CSV report, explicit missing/stale states,
  unchanged CRS scores, settings-based unverified shortlist.
- Configurable volume/OI/vendor-liquidity/earnings/mean-IV thresholds; preserved
  vendor fields and separate price-age/retrieval-age limits.
- Session history with rank movement, entrants/departures and gaps; repeated
  runs replace the same session. Synthetic and public histories stay separate.
- Daily user-run refresh/fetch/report workflow stops on failure without old-data
  fallback. Cached dashboard reuses local data without downloads.
- Optional native OS storage for OTA and separately profiled Tradier credentials.
- Standalone monthly ATM Tradier probe prepared with pure selection/spread tests;
  dashboard integration waits for the user's draft approval. Bid, ask, OI and
  current volume per leg; average contract volume unavailable.
- Source access inventory: [SOURCES.md](SOURCES.md). Metric definitions stay
  explicitly unverified. [CHAIN_PLAN.md](CHAIN_PLAN.md) records monthly rules.

## Remaining external validation

1. User reviews the synthetic dashboard and runs cached dashboard on real files.
2. User validates fresh daily output and optional OS credential store locally.
3. After draft approval, user tests the isolated Tradier probe; integrate its
   contract metrics only after schema, expiration, delay and quote times check out.
4. Verify live OTA full-page continuation, metric definitions and a defensible
   options-volume ETF universe. Current 50 ETF list remains a starter watchlist.
5. Run prepared CI on user push; confirm native OS behavior. No performance or
   profitability validation is claimed.

## OTA capture redesign

Capture preserves bounded response bodies and original row values; field-type
profiles and versioned normalization are separate outputs. `ota-process` replays
local captures without network/authentication. Dashboard accepts completed raw
captures and exposes processing statuses; incomplete runs cannot become reports.
125 guarded offline tests passed, including byte preservation, mixed-field profile
counts, partial failure retention, sanitized profile summaries and offline replay.
Legacy files remain readable but cannot restore previously discarded values.

## Shared ingestion policy adoption

Policy revision 3 applies capture/profile/normalize/business-rule separation to
all external fetches, including public library adapters. OTA implements the first
capture/profile/replay increment. Tradier now has initial raw-body capture and field profiles; replay and broader
normalization remain pending. Public price/constituent adapters still need adoption; cross-run schema-drift comparison and retention controls
are requirements, not implemented features. Library-returned data cannot be
claimed to preserve wire-level bytes unless the actual transport exposes them.
Agents must explain applicable established practices and project-specific
tradeoffs when analyzing requirements and recommending solutions.

References: [layered raw/refined/business data](https://learn.microsoft.com/en-us/azure/databricks/lakehouse/medallion)
and [schema evolution and rescued fields](https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/schema).
These are established architectural patterns, not a mandate to adopt Databricks
or a universal requirement to accept unusable data into calculations.
