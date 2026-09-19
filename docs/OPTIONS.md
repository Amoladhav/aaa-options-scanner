# Offline options enrichment

This increment prepares a normalized input boundary for later OTA integration.
It makes no OTA requests and does not implement Chrome session-token acquisition.
Provider metric definitions, aggregation and supported authentication are unresolved.
Options values never change CRS scores, ranks or candidate labels.

Run from the repository root (Bash/WSL; no dependencies required):

```bash
python3 -I -S run.py demo --with-options
```

Native Windows PowerShell:

```powershell
py -3 -I -S run.py demo --with-options
```

The report includes a separate options table and `options.csv`, in momentum rank
order. The snapshot embeds validated options input so cached replay reproduces
the join. The usual progress stage and JSONL logging apply. No token is needed.

For locally prepared, normalized data, use `cached --snapshot PATH --options-file
PATH` or the user-run `refresh --profile public --options-file PATH`. Do not pass
raw authenticated responses, browser exports or files containing credentials.
Keep local inputs in ignored `artifacts/`. Inputs are limited to 2 MB / 10,000 rows.
Unknown keys, duplicate normalized symbols and invalid values fail the run with
`INVALID_OPTIONS_INPUT`; they are not silently replaced with synthetic data.

The exact version-1 shape is:

```json
{
  "schema_version": 1,
  "source": "user_supplied",
  "methodology": "unverified",
  "rows": [
    {
      "symbol": "SPY",
      "as_of": "2026-09-17",
      "iv_rank": null,
      "iv_percentile": null,
      "option_volume": null,
      "open_interest": null
    }
  ]
}
```

All keys are required. IV fields are distinct 0–100 values, not fractions; volume
and open interest are nonnegative integer contract counts, not dollars. Unknown
values must be `null`; zero is valid. There is no alias substitution, derived IV
history, spread estimate or liquidity qualification. Contract/expiry coverage and
provider methodology are deliberately unverified: do not use this input contract
to claim comparable or actionable metrics until a provider-specific version defines
them. `source: synthetic` is required for synthetic price snapshots; public price
snapshots require `user_supplied`. This is a declaration, not provenance verification.

`as_of` is the declared observation session (canonical YYYY-MM-DD, weekday).
Same-session rows are `aligned` or `partial`. Earlier/later rows are `stale` or
`future`, with their values withheld from the joined report. Absent symbols are
`missing`. This checks session labels only, not exchange holidays, timestamps,
intraday quote age, publication delays or historical availability. It is not a
point-in-time backtest data adapter. Extra valid symbols are retained in the input
snapshot but only ranked symbols appear in the joined report.

# OTA access investigation: user-run only

The owner reports website access with a Chrome session token, but no API access.
Public [OTA support information](https://www.otatrade.com/pricing/) identifies the
User Menu support ticket system and support@tradetoolsupport.com. A supported
automation/authentication method has not been established.

Ask support whether personal scripted, read-only screener access is permitted and
supported, and request the authentication method, expiry, renewal, revocation and
rate limits. A website session persisting does not prove a token is long-lived:
the browser might refresh it or use a separate cookie.

Until that method is established, test only the normal website flow locally:

1. Sign in normally in Chrome. Open Developer Tools, Network, Fetch/XHR. Load a
   read-only screener you already use. Observe HTTP status and authentication
   header **names only**; do not copy values or export requests, HAR or cookies.
2. Reload the screener and note whether it loads without a new login.
3. Close all Chrome windows, reopen and repeat. Record elapsed time and whether a
   login was required; repeat the next day if useful. Browser background processes
   and session restoration mean this is not a controlled token-expiry test.
4. Sign out using the website, then reload the protected page. Note whether a login
   is required. This does not establish server-side revocation of old tokens.
5. Sign back in normally. Share only the status/login-needed observations and any
   provider documentation, never token values or raw responses.

Token extraction/storage and scripted expiry/revocation tests remain pending the
supported method. Any later authenticated test will be explicitly user-run and
produce an allowlisted report; agents will not execute it.
