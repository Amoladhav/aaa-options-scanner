# ATM monthly option spreads: draft contract

Research checked 2026-09-19. This is a proposed output and adapter contract;
live chain validation and dashboard integration are pending the owner's review
of the first dashboard. No authenticated request was made for this research.

## Provider feasibility

| Provider | Sign-in/account | Feasibility and limits |
| --- | --- | --- |
| yfinance / Yahoo Finance | No account or API key in the ordinary library workflow | `Ticker.options` lists dates; `Ticker.option_chain(date)` supplies calls, puts and an underlying quote. Calls/puts include strike, bid, ask, volume and open interest. The exposed rows lack bid/ask timestamps and an explicit monthly/weekly classification. Suitable for an indicative prototype, with quote freshness unverified. |
| Tradier | Explicit account sign-in and API token required | Expiration metadata and chains support a better specified implementation; option quotes expose expiration type, contract size and separate bid/ask times. Production brokerage market data is real time; sandbox is delayed 15 minutes. An existing token does not identify its environment: the user must select it explicitly. |

Sources: [yfinance quick start](https://ranaroussi.github.io/yfinance/),
[maintainer's option-chain implementation](https://github.com/ranaroussi/yfinance/blob/main/yfinance/ticker.py),
[Tradier environments](https://docs.tradier.com/docs/endpoints),
[Tradier market-data entitlements](https://docs.tradier.com/docs/market-data).
yfinance is an unofficial research tool using publicly accessible Yahoo APIs,
not a supported open-data service; its documentation describes personal-use
restrictions. No claim of reliable current Yahoo chain access has been tested here.

## Proposed output and selection

Interpret "spread" as **ask minus bid for each option**, not the price difference
between a call and a put or a multi-leg trade. Display separate call and put
columns: bid, ask, dollar spread and spread percent of midpoint. Dollar quotes
are per share; optional contract-dollar amounts require a verified multiplier.

For the first version, limit selection to ordinary US stock/ETF contracts.
Use the earliest available future standard monthly expiration, excluding the
current New York calendar date (a daily after-close workflow). Use one shared
strike present in both call and put chains, minimizing absolute distance from
the provider's contemporaneous underlying price. Break exact ties toward the
lower strike, record the rule and underlying observation time, and do not choose
a different strike merely because its quotes look better.

Render `*` as our monthly-expiration display marker only after classification;
it is not an API date suffix. Tradier's `expiration_type=standard` provides
direct metadata. With Yahoo, classify only against a verified stock/ETF monthly
calendar and explicitly label the classification as calendar-derived. Do not
assume that every third Friday is available: holidays shift trading dates.
Do not apply this stock/ETF rule to AM-settled index or volatility products.
See the [OIC expiration glossary](https://www.optionseducation.org/referencelibrary/optionsglossary?filter=e)
and [2026 OCC/OIC expiration calendar](https://www.optionseducation.org/getmedia/78d096fb-a61e-4120-b84a-35b631b58c4b/2026-Expiration-Calendar-12-16-FINAL.pdf?ext=.pdf).

Example below is synthetic and specifies formatting only. Bid and ask remain
separate columns for both legs; spreads are additional derived columns:

| Symbol | Monthly expiry | Underlying | ATM strike | Leg | Bid | Ask | Spread | Spread / mid | Open interest | Current volume | Average contract volume | Quote status |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| DEMO | 2026-10-16* | 100.20 | 100 | Call | 3.10 | 3.20 | 0.10 | 3.17% | 1200 | 340 | unavailable | synthetic |
| DEMO | 2026-10-16* | 100.20 | 100 | Put | 2.90 | 3.00 | 0.10 | 3.39% | 950 | 280 | unavailable | synthetic |

Open interest and current option volume are contract counts for each selected
leg. Missing counts remain null; negative or fractional counts are rejected.
Neither chain snapshot establishes an average contract volume, so that field
remains null with an explicit unavailable status. OTA's `avgVol30d` describes
underlying stock/ETF volume and must not be relabeled as option-contract average
volume. The default display follows usual chain conventions: current contract volume
and open interest for each leg, with underlying average volume shown separately
and its period labeled. No historical contract average is invented.

Formula: `spread = ask - bid`; `spread_pct = 100 * spread / ((ask + bid) / 2)`.
Missing, nonfinite, negative, crossed or zero-sided quotes produce an explicit
unusable status, never a zero spread. Preserve raw allowed values for user
inspection. Do not replace missing bid/ask with last trade prices. Stale quotes,
delayed sandbox quotes and unknown Yahoo quote times remain visibly distinct;
last-trade time is not bid/ask time. Reject ambiguous adjusted/duplicate contracts
instead of assuming a 100-share deliverable. A valid spread does not imply that
a trade is executable at that price or size.

## Tradier read-only adapter contract

Use explicit `sandbox` or `production` configuration, fixed HTTPS hosts, Bearer
authentication and `Accept: application/json`. No automatic environment switch,
redirect, alternate provider or synthetic-data fallback on failure.

1. `GET /v1/markets/options/expirations` with `symbol`,
   `includeAllRoots=false`, `expirationType=false`. The current probe confirms
   monthly status from chain metadata and bounds inspection to 32 upcoming chains.
2. `GET /v1/markets/options/chains` with `symbol`, selected `expiration`,
   `greeks=true`. Retain verified standard contracts and exclude unsupported
   adjusted roots/deliverables. The live enhanced-expiration response shape must
   still be validated; do not invent fields from the query parameter names.
3. `GET /v1/markets/quotes` for the underlying, retaining price/time needed for
   ATM selection. Chain option quote fields of interest are `symbol`, `underlying`,
   `strike`, `option_type`, `expiration_date`, `expiration_type`, `contract_size`,
   `bid`, `ask`, `bid_date`, `ask_date`, `volume`, `open_interest` and root metadata.

References: [expirations](https://docs.tradier.com/reference/brokerage-api-markets-get-options-expirations),
[chains](https://docs.tradier.com/reference/brokerage-api-markets-get-options-chains),
[quote fields](https://docs.tradier.com/docs/quotes).
Market-data limits are currently 120 requests/minute in production and 60 in
sandbox, per token; bound concurrency and respect rate-limit responses. See
[rate limits](https://docs.tradier.com/docs/rate-limiting).

## Local credentials and validation boundary

The `tradier-token set --profile production` hidden-input command is prepared to store the user's own key in an explicitly
selected native OS keyring backend, with separate service names for production
and sandbox. Windows uses Credential Locker, macOS Keychain, Linux Secret Service;
WSL requires its own functioning Secret Service (there is no Tradier plaintext fallback).
No plaintext-backend fallback, token argument, checked-in file or debug tracing.
Do not reuse the OTA service name. Native-keyring setup and live adapter checks
remain user-run. Exact runnable commands are in [README](../README.md).

Tradier says individual settings-page tokens do not expire automatically, unlike
partner OAuth access tokens; they can still be revoked/replaced. See
[Tradier FAQ](https://docs.tradier.com/docs/faq). This differs from OTA's observed
session-bound token. Store only the token appropriate to the chosen environment.

First live acceptance should use one liquid stock/ETF during its regular session:
verify expiration/type, a shared ATM strike, two valid bid/ask pairs, timestamp
units and delay classification. Save provider data for the user locally and an
allowlisted counts/status/error report for agent review. Never share raw responses,
headers or the key. Offline fixtures must cover holiday shifts, ties, missing
legs, adjusted contracts, invalid/crossed/zero quotes, stale quotes and wrong
environment authentication. Dashboard integration follows user approval.

## Implemented validation additions

ATM strike is explicit at the top level and on each selected leg. Returned Greeks
are retained verbatim with status and provider cadence labels, not used as ranking
inputs. Sandbox cannot validate Greek availability; production user testing is
pending. Raw response bodies and field profiles now precede strict selection.
