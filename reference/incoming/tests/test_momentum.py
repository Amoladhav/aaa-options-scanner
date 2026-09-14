"""Tests for the cross-sectional momentum z-score ranker."""
from __future__ import annotations

from trading_scanner.config import load_momentum_config
from trading_scanner.momentum import (
    MomentumInput,
    _winsorize,
    _zscore,
    confirm_persistence,
    rank_universe,
    tail_changes,
)

CFG = load_momentum_config()


def _universe(n=30):
    """Deterministic spread: symbol i gets returns scaling with i (S00 weakest .. S29 strongest)."""
    sectors = ["Tech", "Energy", "Health"]
    out = []
    for i in range(n):
        base = (i - n / 2) / n          # -0.5 .. +0.5
        out.append(MomentumInput(
            symbol=f"S{i:02d}", sector=sectors[i % 3],
            returns={"r21": base * 0.10, "r63": base * 0.20, "r126": base * 0.30},
        ))
    return out


def test_zscore_and_winsorize():
    assert _zscore([1, 1, 1]) == [0.0, 0.0, 0.0]
    z = _zscore([0, 10])
    assert z[0] < 0 < z[1]
    # an extreme value gets pulled in by winsorize
    w = _winsorize([0, 0, 0, 100], 1.5)
    assert max(w) < 100


def test_momentum_tails_and_ranking():
    res = rank_universe(_universe(30), CFG)
    assert res.universe_size == 30
    # strongest names are long, weakest are short
    assert "S29" in res.longs and "S28" in res.longs
    assert "S00" in res.shorts and "S01" in res.shorts
    # ranked descending by composite z; top of list is a long
    assert res.ranked[0].bias == "long"
    assert res.ranked[-1].bias == "short"
    # ~10% each tail of 30 -> 3 each
    assert len(res.longs) == 3 and len(res.shorts) == 3


def test_reversal_flips_direction():
    rev = load_momentum_config()
    rev.direction = "reversal"
    res = rank_universe(_universe(30), rev)
    # now the WEAKEST names are the longs
    assert "S00" in res.longs and "S29" in res.shorts


def test_sector_table_ranked():
    res = rank_universe(_universe(30), CFG)
    assert res.sectors and res.sectors[0]["rank"] == 1
    zs = [s["mean_z"] for s in res.sectors]
    assert zs == sorted(zs, reverse=True)        # best -> worst
    assert sum(s["n"] for s in res.sectors) == 30


def test_empty_universe():
    res = rank_universe([], CFG)
    assert res.universe_size == 0 and res.ranked == []


def test_snapshot_write_and_load_prior(tmp_path):
    from trading_scanner.momentum_snapshot import load_prior, write_snapshot
    res = rank_universe(_universe(30), CFG)
    write_snapshot("2026-08-10", res, root=tmp_path)
    write_snapshot("2026-08-11", res, root=tmp_path)
    prior = load_prior("2026-08-12", root=tmp_path)      # both are before 08-12
    assert len(prior) == 2
    assert set(prior[-1].longs) == set(res.longs)
    # a snapshot dated today is NOT counted as prior
    assert len(load_prior("2026-08-11", root=tmp_path)) == 1


def test_persistence_confirms_after_min_days():
    base = rank_universe(_universe(30), CFG)          # S29.. are longs, S00.. shorts
    # 3 identical prior runs + current => stable longs have streak 4 >= 3 -> confirmed
    hist = [base, base, base]
    res = confirm_persistence(hist, base, min_days=3)
    assert set(res["confirmed_long"]) == set(base.longs)
    assert res["provisional_long"] == []
    assert res["streaks"][base.longs[0]] >= 3

    # a name freshly in the tail (no history) is provisional
    fresh = rank_universe(_universe(30), CFG)
    res2 = confirm_persistence([], fresh, min_days=3)   # no history -> streak 1 each
    assert set(res2["provisional_long"]) == set(fresh.longs)
    assert res2["confirmed_long"] == []


def test_tail_changes_tracks_rotation():
    # shift every symbol's returns up so the ordering rotates between runs
    prev = rank_universe(_universe(30), CFG)
    shifted = _universe(30)
    for i in shifted:
        i.returns = {k: v + 0.05 for k, v in i.returns.items()}  # uniform shift = same ranking
    curr = rank_universe(shifted, CFG)
    d = tail_changes(prev, curr)
    # uniform shift doesn't change ranking -> tails identical, all stable
    assert d["long_entered"] == [] and d["short_entered"] == []
    assert set(d["long_stable"]) == set(prev.longs)

    # now make S00 (was weakest) the strongest -> it enters longs, exits shorts
    bumped = _universe(30)
    bumped[0].returns = {"r21": 9.0, "r63": 9.0, "r126": 9.0}
    curr2 = rank_universe(bumped, CFG)
    d2 = tail_changes(prev, curr2)
    assert "S00" in d2["long_entered"]
    assert "S00" in d2["short_exited"]
