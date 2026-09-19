# Source access and metric boundaries

Reviewed 2026-09-19. INBOX implements Finviz Elite and OTA; Tradier is only a
proposed adapter there. yfinance and Wikipedia are used by this replacement.

## Public access: no personal account or sign-in

| Source | Use | Limits |
| --- | --- | --- |
| [yfinance / Yahoo](https://ranaroussi.github.io/yfinance/) | Adjusted prices and option-chain bid/ask | Unofficial client, not a guaranteed open Yahoo API. Personal-use access; availability and quote freshness need validation. |
| [Wikipedia / MediaWiki](https://www.mediawiki.org/wiki/API:REST_API/Reference/en) | Current S&P membership | Public content, not an authoritative historical index feed. |
| [Finviz public pages](https://elite.finviz.com/elite) | Public browsing | Does not provide the export/API capability used by INBOX. |

## Account, subscription or sign-in required

| Source | Requirements | Status |
| --- | --- | --- |
| [Finviz Elite](https://elite.finviz.com/help/faq) | Account, sign-in, Elite subscription/trial, export authentication | INBOX has a CSV adapter; not connected to this runtime. |
| [OTA Trade](https://www.otatrade.com/pricing/) | Account, sign-in, entitled subscription/trial, current session token | User verified 77 rows; token expires with session. No supported public API documentation established. |
| [Tradier](https://docs.tradier.com/docs/endpoints) | Brokerage account and API token, acquired after sign-in; sandbox also requires account | Standalone probe prepared; dashboard integration awaits draft approval. [Brokerage data is real-time; sandbox is delayed](https://docs.tradier.com/docs/market-data). |

## Vendor metrics are not interchangeable

CRS uses only adjusted daily prices and cross-sectional ranks. OTA enrichment
never changes the CRS score. Numeric filter matches are research selections,
not calibrated probabilities or validated trading recommendations.

| OTA field | Display/use | Unresolved definition |
| --- | --- | --- |
| `meanIvPcnt` | Vendor mean IV, percent-named units | Contract selection, weighting, quote cutoff |
| `ivHi1YrPcnt`, `ivLow1YrPcnt` | Vendor annual high/low fields | Underlying IV series and methodology; not IV rank or percentile |
| `ivGauge` | Vendor code | Category interpretation |
| `spreadLiquidityPcnt` | Vendor liquidity metric | Not a contract bid/ask spread; aggregation unknown |
| `totalOpenInterest`, `totalOptionsVolume` | Vendor counts | Included contracts/expiries and update timing |
| `daysToEarnings` | Vendor days count | Event timestamp and calendar conventions |

Unknown/missing fields stay null. No current official metric definitions were
established during this review. OTA retrieval time does not prove quote freshness.
The old INBOX zero placeholder for unavailable bid/ask spreads is not reused.

[Monthly ATM spread plan](CHAIN_PLAN.md) records provider differences and selection
rules. Real bid/ask spreads must come from a specific call and put contract.
