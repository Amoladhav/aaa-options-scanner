"""Cross-sectional momentum (z-score) ranker.

Ranks a universe by a multi-horizon momentum composite, standardizes it into
z-scores, and classifies the distribution tails (top/bottom decile) as long/short.
Pure Python, data-source-agnostic: the caller supplies per-symbol horizon returns
(from Finviz Perf columns in v1, or exact adjusted-close returns later).

Construction (see momentum-zscore-framework.md):
  1. per-horizon cross-sectional z-scores (winsorized), optionally vol-adjusted
  2. composite = Σ weightₕ · zₕ  (1-month double-weighted by default)
  3. final z-score of the composite
  4. direction: momentum uses final z; reversal negates it
  5. tails: top/bottom `tail_pct` decile -> long / short
  6. sector aggregation: mean final z per sector -> best/worst sectors
"""
from __future__ import annotations

import statistics
from typing import Optional

from .minimodel import BaseModel, Field


class MomentumInput(BaseModel):
    symbol: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    returns: dict[str, float] = Field(default_factory=dict)  # e.g. {"r21":.., "r63":.., "r126":..}
    vol: Optional[float] = None                              # realized vol (for vol_adjust)


class RankedSymbol(BaseModel):
    symbol: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    composite_z: float          # final z-score (momentum orientation; + = stronger)
    percentile: float           # 0..1 of the direction-adjusted score
    bias: str                   # "long" | "short" | "neutral"
    horizon_z: dict[str, float] = Field(default_factory=dict)


class MomentumResult(BaseModel):
    ranked: list[RankedSymbol]
    sectors: list[dict]         # [{sector, mean_z, n, rank}] best -> worst
    longs: list[str]
    shorts: list[str]
    universe_size: int


def _zscore(values: list[float]) -> list[float]:
    if not values:
        return []
    m = statistics.mean(values)
    sd = statistics.pstdev(values)
    if sd == 0:
        return [0.0] * len(values)
    return [(v - m) / sd for v in values]


def _winsorize(values: list[float], sigma: float) -> list[float]:
    if not sigma or sigma <= 0 or not values:
        return values
    m = statistics.mean(values)
    sd = statistics.pstdev(values)
    if sd == 0:
        return values
    lo, hi = m - sigma * sd, m + sigma * sd
    return [min(max(v, lo), hi) for v in values]


def rank_universe(inputs: list[MomentumInput], cfg) -> MomentumResult:
    """Rank a universe. `cfg` is a MomentumConfig (direction, horizons, etc.)."""
    n = len(inputs)
    if n == 0:
        return MomentumResult(ranked=[], sectors=[], longs=[], shorts=[], universe_size=0)

    symbols = [i.symbol for i in inputs]
    horizon_z: dict[str, dict[str, float]] = {s: {} for s in symbols}

    # 1 — per-horizon cross-sectional z (missing -> horizon mean; optional vol-adjust + winsorize)
    for h in cfg.horizons:
        raw: list[Optional[float]] = []
        for i in inputs:
            r = i.returns.get(h)
            if cfg.vol_adjust and r is not None and i.vol:
                r = r / i.vol
            raw.append(r)
        present = [x for x in raw if x is not None]
        fill = statistics.mean(present) if present else 0.0
        filled = [x if x is not None else fill for x in raw]
        zs = _zscore(_winsorize(filled, cfg.winsorize_sigma))
        for s, z in zip(symbols, zs):
            horizon_z[s][h] = z

    # 2 — weighted composite, then 3 — final z
    composite = [sum(cfg.horizons[h] * horizon_z[i.symbol][h] for h in cfg.horizons) for i in inputs]
    final_z = _zscore(composite)

    # 4 — direction-adjusted score for tail selection
    eff = final_z if cfg.direction == "momentum" else [-x for x in final_z]

    # percentile rank (mid-rank) of the effective score
    order = sorted(range(n), key=lambda k: eff[k])
    pct = [0.0] * n
    for rank_idx, k in enumerate(order):
        pct[k] = (rank_idx + 0.5) / n

    # 5 — classify tails
    ranked: list[RankedSymbol] = []
    longs, shorts = [], []
    for idx, i in enumerate(inputs):
        p = pct[idx]
        if p >= 1 - cfg.tail_pct:
            bias = "long"
            longs.append(i.symbol)
        elif p <= cfg.tail_pct:
            bias = "short"
            shorts.append(i.symbol)
        else:
            bias = "neutral"
        ranked.append(RankedSymbol(
            symbol=i.symbol, sector=i.sector, industry=i.industry,
            composite_z=round(final_z[idx], 4), percentile=round(p, 4), bias=bias,
            horizon_z={h: round(horizon_z[i.symbol][h], 4) for h in cfg.horizons},
        ))
    ranked.sort(key=lambda r: r.composite_z, reverse=True)

    # 6 — sector aggregation (best -> worst by mean momentum z)
    by_sector: dict[str, list[float]] = {}
    for idx, i in enumerate(inputs):
        if i.sector:
            by_sector.setdefault(i.sector, []).append(final_z[idx])
    sectors = [{"sector": s, "mean_z": round(statistics.mean(v), 4), "n": len(v)}
               for s, v in by_sector.items()]
    sectors.sort(key=lambda d: d["mean_z"], reverse=True)
    for rnk, d in enumerate(sectors, 1):
        d["rank"] = rnk

    return MomentumResult(ranked=ranked, sectors=sectors, longs=longs, shorts=shorts,
                          universe_size=n)


def _streak(sets: list[set], sym: str) -> int:
    """Consecutive runs (ending at the most recent) that `sym` is in `sets`."""
    c = 0
    for s in reversed(sets):
        if sym in s:
            c += 1
        else:
            break
    return c


def confirm_persistence(history: list[MomentumResult], current: MomentumResult,
                        min_days: int) -> dict:
    """Split current tail members into confirmed vs provisional by persistence.

    A name is CONFIRMED once it has been in the tail for `min_days` consecutive runs
    (including the current one) — this is the flicker filter for acting on entrants.
    `history` is prior runs in chronological order (oldest → newest), NOT including
    `current`. Returns confirmed/provisional lists per tail plus per-symbol streaks.
    """
    seq = history + [current]
    long_sets = [set(r.longs) for r in seq]
    short_sets = [set(r.shorts) for r in seq]

    def split(members: list[str], sets: list[set]):
        confirmed, provisional, streaks = [], [], {}
        for sym in members:
            st = _streak(sets, sym)
            streaks[sym] = st
            (confirmed if st >= min_days else provisional).append(sym)
        return confirmed, provisional, streaks

    cl, pl, sl = split(current.longs, long_sets)
    cs, ps, ss = split(current.shorts, short_sets)
    return {
        "confirmed_long": cl, "provisional_long": pl,
        "confirmed_short": cs, "provisional_short": ps,
        "streaks": {**sl, **ss},
    }


def tail_changes(previous: MomentumResult, current: MomentumResult) -> dict:
    """Diff two runs' decile tails: who ENTERED / EXITED / stayed in each tail.

    Tail entrants are the fresh signals; exits are names losing their edge. Feed
    two dated snapshots (e.g. today vs the last run) to see the rotation you care
    about. Combine with a persistence rule (in-tail N days) to filter daily flicker.
    """
    pl, ps = set(previous.longs), set(previous.shorts)
    cl, cs = set(current.longs), set(current.shorts)
    return {
        "long_entered": sorted(cl - pl),
        "long_exited": sorted(pl - cl),
        "long_stable": sorted(cl & pl),
        "short_entered": sorted(cs - ps),
        "short_exited": sorted(ps - cs),
        "short_stable": sorted(cs & ps),
    }
