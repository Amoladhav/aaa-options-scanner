# Provider pacing and local feedback

All user-run OTA, Tradier and public price-fetch entry points share one request
governor. Existing commands stay the same. This favors conservative operation;
provider access, valid sessions and successful responses cannot be guaranteed.

| Provider | Initial wait before each HTTP attempt |
| --- | --- |
| OTA | 5 seconds |
| Tradier production | 2 seconds |
| Tradier sandbox | 3 seconds |
| Yahoo through yfinance | 10 seconds |
| Wikipedia constituents | 2 seconds |

Response time is additional. Requests are sequential; yfinance threading is
disabled and its supported custom session paces GET/POST calls and Yahoo HTTPS
redirect hops. Unsupported redirects stop. Optional dependency integration still
needs user-run live validation against the pinned yfinance version.

## Feedback and stopping rules

- Rate limits, transient server failures and network failures double the learned
  interval, up to one hour. An already slower interval is preserved. Successful
  or fast requests never automatically increase the request rate.
- `Retry-After` delta seconds and HTTP dates on 429/503 responses are respected.
  A 429 adds at least five minutes of cooldown; other transient failures add at
  least 30 seconds. Tradier quota headers can increase spacing or delay a request
  until its quota resets, with a safety margin.
- GET requests allow at most one retry through this governor. OTA POST requests
  are not automatically replayed. An exhausted retry opens a circuit for the rest
  of that provider session, including further calls made by a library.
- Authentication/access rejection stops without retry. Schema/selection errors do
  not trigger network retries. Existing per-symbol batch failure handling remains.
- A wait over 15 minutes stops with `THROTTLE_COOLDOWN_ACTIVE` instead of silently
  shortening the provider deadline. Rerunning early respects the stored cooldown.
  Rerun manually after the cooldown; there is no scheduler or automatic batch resume.

Tradier documents shared token quotas and quota headers in its
[rate-limit guide](https://docs.tradier.com/docs/rate-limiting). Other applications
using the same credentials also consume that quota. These defaults are local
policy, not a claim that each provider guarantees a particular rate.

## Estimates, actual time and local files

At provider-session startup, stdout shows the pacing interval, estimated remaining
time and estimated completion in the machine's local timezone. Estimates include
response latency, learned requests per work unit and a 50% margin. OTA initially
uses the configured page limit; Yahoo starts with 80 requests per 40-symbol batch;
Tradier starts with 14 per symbol. These are provisional workload estimates, not
upper bounds. Observations refine workload/latency estimates independently of the
request interval. Final output includes actual elapsed time and throttle counters.
Logs keep the existing schema version 2 with an additive `estimate` field.

Local files under `artifacts/throttling/` are covered by `.gitignore`:

- `<provider>.json`: current interval, cooldown, observed latency/workload and last
  provider-session duration. This is reused across runs in this workspace.
- `history/<provider>-<id>.json`: actual session duration, completion timestamp,
  request/retry/rate-limit counts, wait time and session outcome. A finished
  request session does not imply that every symbol produced usable data.
- `<provider>.lock`: prevents concurrent fetch sessions for the same provider and
  profile in this workspace. It is removed on normal exit or handled cancellation.

Only implementation, defaults, synthetic tests and documentation belong in Git.
Feedback contains numeric operational measurements, not tokens, cookies, symbols,
request URLs or response bodies. It is still local user data; agents should use
sanitized review reports instead of opening runtime feedback or logs.

`THROTTLE_BUSY` means another local fetch holds the lease. After a crash, confirm
that no fetch process remains before removing only that provider's stale `.lock`.
Do not delete learned feedback merely to bypass a cooldown. Invalid feedback stops
with `THROTTLE_STATE_INVALID`; preserve it locally for diagnosis and repair it
before rerunning. Feedback write failures also stop fetching.

The lease does not coordinate separate clones, machines or other applications.
A future shared job service must coordinate provider/account quotas across those
workers. Batch resume, cross-machine coordination and automatic speed increases
are not implemented.

Offline tests cover virtual-time pacing, persisted slowdowns, quotas, retry
exhaustion, long cooldowns, corrupt state, leases, interruption, public redirects
and provider HTTP feedback. Live checks remain user-run and pending.
