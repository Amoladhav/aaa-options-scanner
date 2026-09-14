"""Pure momentum calculation, derived from the reviewed incoming construction.

Returns are fractions; z-scores and percentiles are dimensionless. Stocks and
ETFs have separate cross-sectional distributions. There is no trading execution.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
import math
import re
import statistics

HORIZONS = (21, 63, 126)
WEIGHTS = (0.50, 0.25, 0.25)
SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}\Z")


class DataError(ValueError):
    """Arguments are fixed safe codes, never provider responses."""


def normalize_symbol(value: str) -> str:
    symbol = value.strip().upper().replace(".", "-")
    if not SYMBOL.fullmatch(symbol):
        raise DataError("INVALID_SYMBOL")
    return symbol


def normalize_universe(rows: list[dict]) -> list[dict]:
    result = {}
    for row in rows:
        symbol = normalize_symbol(row["symbol"])
        group = row["group"]
        if group not in {"stock", "etf"}:
            raise DataError("INVALID_GROUP")
        clean = {"symbol": symbol, "group": group,
                 "company": str(row.get("company", "")),
                 "sector": str(row.get("sector", "")),
                 "sector_etf": bool(row.get("sector_etf", False))}
        if symbol in result and result[symbol] != clean:
            raise DataError("CONFLICTING_SYMBOL")
        result[symbol] = clean
    return [result[s] for s in sorted(result)]


def zscore(values: list[float]) -> list[float]:
    if not values:
        return []
    sd = statistics.pstdev(values)
    mean = statistics.mean(values)
    return [(v - mean) / sd for v in values] if sd else [0.0] * len(values)


def clipped_zscore(values: list[float]) -> list[float]:
    mean, sd = statistics.mean(values), statistics.pstdev(values)
    return zscore([min(max(v, mean - 3 * sd), mean + 3 * sd) for v in values])


def midrank_percentiles(values: list[float]) -> list[float]:
    # Equal values share the average ordinal rank, independent of input order.
    counts, percentiles, before = Counter(values), {}, 0
    for value in sorted(counts):
        count = counts[value]
        percentiles[value] = (before + count / 2) / len(values)
        before += count
    return [percentiles[v] for v in values]


def rank_returns(rows: list[dict], minimum: int = 20) -> list[dict]:
    """Rank valid, complete returns. Caller supplies one peer group at a time."""
    if len(rows) < minimum:
        return []
    if len({r["symbol"] for r in rows}) != len(rows):
        raise DataError("DUPLICATE_SYMBOL")
    for row in rows:
        if any(not math.isfinite(row[f"r{h}"]) for h in HORIZONS):
            raise DataError("INVALID_RETURN")
    horizon_z = [clipped_zscore([r[f"r{h}"] for r in rows]) for h in HORIZONS]
    scores = zscore([sum(w * z[i] for w, z in zip(WEIGHTS, horizon_z))
                     for i in range(len(rows))])
    percentiles = midrank_percentiles(scores)
    result = []
    for i, row in enumerate(rows):
        p = percentiles[i]
        result.append({**row, "score": scores[i], "percentile": p,
                       "bias": "long" if p >= .9 else "short" if p <= .1 else "neutral",
                       **{f"z{h}": horizon_z[j][i] for j, h in enumerate(HORIZONS)}})
    result.sort(key=lambda r: (-r["score"], r["symbol"]))
    return [{"rank": i + 1, **r} for i, r in enumerate(result)]


def completed_sessions(schedule: list[tuple[str, str]], now: datetime) -> list[str]:
    """Use official calendar closes plus one hour for daily-data publication.

Timezone-aware close times handle DST and early closes. Never use today's
unfinished daily bar. This is a publication buffer, not a freshness guarantee.
"""
    if now.utcoffset() is None:
        raise DataError("NAIVE_TIMESTAMP")
    result = []
    for session, close_text in schedule:
        close = datetime.fromisoformat(close_text)
        if close.utcoffset() is None:
            raise DataError("NAIVE_TIMESTAMP")
        if close + timedelta(hours=1) <= now:
            result.append(session)
    return sorted(set(result))


def calculate(snapshot: dict) -> dict:
    """Calculate from an explicit, self-contained snapshot; never fetch or fill."""
    if snapshot.get("schema_version") != 1 or snapshot.get("profile") not in {"synthetic", "public"}:
        raise DataError("INVALID_SNAPSHOT")
    cutoff = date.fromisoformat(snapshot["as_of"])
    all_sessions = snapshot["sessions"]
    if all_sessions != sorted(set(all_sessions)):
        raise DataError("INVALID_SESSION_ORDER")
    if any(date.fromisoformat(d).weekday() >= 5 for d in all_sessions):
        raise DataError("WEEKEND_SESSION")
    sessions = [d for d in all_sessions if date.fromisoformat(d) <= cutoff]
    if len(sessions) < 127 or sessions[-1] != cutoff.isoformat():
        raise DataError("INSUFFICIENT_CALENDAR")
    window = sessions[-127:]
    universe = normalize_universe(snapshot["universe"])
    prices = snapshot["prices"]
    valid, excluded = [], []
    for member in universe:
        symbol = member["symbol"]
        series = prices.get(symbol, {})
        missing = [d for d in window if d not in series]
        reason = "STALE_PRICE" if window[-1] not in series else "MISSING_HISTORY" if missing else None
        if not reason and any(isinstance(series[d], bool) or not isinstance(series[d], (int, float))
                              or not math.isfinite(series[d]) or series[d] <= 0 for d in window):
            reason = "INVALID_PRICE"
        if reason:
            excluded.append({**member, "reason": reason})
            continue
        latest = series[window[-1]]
        returns = {f"r{h}": latest / series[window[-1-h]] - 1 for h in HORIZONS}
        if not all(math.isfinite(v) for v in returns.values()):
            excluded.append({**member, "reason": "INVALID_RETURN"})
            continue
        valid.append({**member, "adjusted_close": latest, **returns})
    ranked = []
    for group in ("stock", "etf"):
        peers = [r for r in valid if r["group"] == group]
        if len(peers) < 20:
            excluded.extend({**r, "reason": "INSUFFICIENT_PEER_GROUP"} for r in peers)
        else:
            ranked.extend(rank_returns(peers))
    return {"as_of": snapshot["as_of"], "profile": snapshot["profile"],
            "membership_observed_at": snapshot["membership_observed_at"],
            "price_source": snapshot["price_source"], "calendar_source": snapshot["calendar_source"],
            "ranked": ranked, "excluded": excluded, "universe_size": len(universe),
            "method": {"horizons_sessions": HORIZONS, "weights": WEIGHTS,
                       "winsorize_sigma": 3, "tail_fraction": .1, "minimum_peers": 20}}
