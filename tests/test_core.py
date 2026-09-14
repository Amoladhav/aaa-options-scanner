import offline_boundary  # Fail closed if this module is collected without isolation.
from datetime import datetime, timezone
import math
import unittest

from trading_scanner.core import (calculate, completed_sessions, DataError,
                                   midrank_percentiles, normalize_universe,
                                   rank_returns, zscore)
from trading_scanner.demo import make_snapshot


class MomentumTests(unittest.TestCase):
    def test_known_population_zscores(self):
        self.assertEqual(zscore([4, 4, 4]), [0, 0, 0])
        self.assertEqual(zscore([0, 10]), [-1, 1])

    def test_matches_reference_on_complete_untied_fixture(self):
        # Same deterministic input construction as incoming test_momentum.py;
        # analytic expected scores avoid importing the historical implementation.
        rows = [{"symbol": f"S{i:02}", "r21": (i-15)/30*.1,
                 "r63": (i-15)/30*.2, "r126": (i-15)/30*.3} for i in range(30)]
        result = rank_returns(rows)
        self.assertEqual([r["symbol"] for r in result[:3]], ["S29", "S28", "S27"])
        self.assertEqual(sum(r["bias"] == "long" for r in result), 3)
        self.assertEqual(sum(r["bias"] == "short" for r in result), 3)
        for row in result:
            i = int(row["symbol"][1:])
            self.assertAlmostEqual(row["score"], (i-14.5)/math.sqrt((30**2-1)/12))

    def test_weighted_horizons_have_expected_direction(self):
        rows = [{"symbol": f"S{i:02}", "r21": i, "r63": -i,
                 "r126": 0.0} for i in range(20)]
        ranked = rank_returns(rows)
        self.assertEqual(ranked[0]["symbol"], "S19")
        self.assertEqual(ranked[-1]["symbol"], "S00")

    def test_weighted_composite_golden_values(self):
        # Balanced +/-1 horizon columns already have mean 0 and stdev 1.
        # 50/25/25 gives composites 1, 0, -.5, -.5; population variance .375.
        patterns = [(1,1,1), (1,-1,-1), (-1,1,-1), (-1,-1,1)]
        rows = [{"symbol": f"S{i:02}", **dict(zip(("r21","r63","r126"), patterns[i%4]))} for i in range(20)]
        ranked = {r['symbol']:r for r in rank_returns(rows)}
        self.assertAlmostEqual(ranked['S00']['score'], 1.632993161855452)
        self.assertEqual(ranked['S01']['score'], 0)
        self.assertAlmostEqual(ranked['S02']['score'], -.816496580927726)
        self.assertEqual(ranked['S02']['percentile'], ranked['S03']['percentile'])

    def test_equal_scores_neutral_and_order_invariant(self):
        rows = [{"symbol": f"S{i:02}", "r21": 0, "r63": 0, "r126": 0} for i in range(20)]
        ranked = rank_returns(rows)
        self.assertEqual(ranked, rank_returns(list(reversed(rows))))
        self.assertTrue(all(r["percentile"] == .5 and r["bias"] == "neutral" for r in ranked))
        self.assertEqual(midrank_percentiles([1, 1, 2, 3]), [.25, .25, .625, .875])

    def test_deduplication_and_yahoo_share_class_names(self):
        a = {"symbol": " brk.b ", "group": "stock"}
        self.assertEqual(normalize_universe([a, a])[0]["symbol"], "BRK-B")
        with self.assertRaises(DataError):
            normalize_universe([a, {"symbol": "BRK-B", "group": "etf"}])

    def test_full_demo_and_exact_endpoint_returns(self):
        snapshot = make_snapshot()
        result = calculate(snapshot)
        self.assertEqual(len(result["ranked"]), 60)
        row = next(r for r in result["ranked"] if r["symbol"] == "S29")
        days, prices = snapshot["sessions"], snapshot["prices"]["S29"]
        for h in (21, 63, 126):
            self.assertEqual(row[f"r{h}"], prices[days[-1]] / prices[days[-1-h]] - 1)

    def test_etf_changes_do_not_change_stock_scores(self):
        snapshot = make_snapshot()
        before = [r for r in calculate(snapshot)["ranked"] if r["group"] == "stock"]
        for d in snapshot["prices"]["E00"]:
            snapshot["prices"]["E00"][d] *= 100
        after = [r for r in calculate(snapshot)["ranked"] if r["group"] == "stock"]
        self.assertEqual(before, after)

    def test_missing_and_stale_prices_excluded_not_filled(self):
        snapshot = make_snapshot()
        del snapshot["prices"]["S00"][snapshot["sessions"][-5]]
        del snapshot["prices"]["S01"][snapshot["as_of"]]
        excluded = {r["symbol"]: r["reason"] for r in calculate(snapshot)["excluded"]}
        self.assertEqual(excluded["S00"], "MISSING_HISTORY")
        self.assertEqual(excluded["S01"], "STALE_PRICE")

    def test_invalid_prices_excluded(self):
        for bad in (0, -1, math.nan, math.inf, True, "100"):
            snapshot = make_snapshot()
            snapshot["prices"]["S00"][snapshot["as_of"]] = bad
            with self.subTest(value=bad):
                self.assertEqual(calculate(snapshot)["excluded"][0]["reason"], "INVALID_PRICE")

    def test_too_small_group_does_not_emit_tail_candidates(self):
        snapshot = make_snapshot()
        snapshot["universe"] = [r for r in snapshot["universe"] if r["group"] == "etf" or r["symbol"] < "S19"]
        result = calculate(snapshot)
        self.assertEqual(len(result["ranked"]), 30)
        self.assertEqual(len(result["excluded"]), 19)
        self.assertTrue(all(r["reason"] == "INSUFFICIENT_PEER_GROUP" for r in result["excluded"]))

    def test_future_prices_cannot_change_results(self):
        snapshot = make_snapshot()
        before = calculate(snapshot)
        snapshot["sessions"].append("2030-01-02")
        for series in snapshot["prices"].values():
            series["2030-01-02"] = 999999
        self.assertEqual(before, calculate(snapshot))

    def test_calendar_duplicates_and_weekends_rejected(self):
        for day in ("2025-01-04", "2025-01-02"):
            snapshot = make_snapshot()
            snapshot["sessions"] = sorted(snapshot["sessions"] + [day])
            with self.assertRaises(DataError):
                calculate(snapshot)

    def test_close_buffer_holiday_weekend_and_early_close(self):
        schedule = [("2025-11-26", "2025-11-26T21:00:00+00:00"),
                    ("2025-11-28", "2025-11-28T18:00:00+00:00")]
        self.assertEqual(completed_sessions(schedule, datetime(2025,11,28,18,30,tzinfo=timezone.utc)), ["2025-11-26"])
        self.assertEqual(completed_sessions(schedule, datetime(2025,11,30,tzinfo=timezone.utc)), ["2025-11-26", "2025-11-28"])
        with self.assertRaises(DataError):
            completed_sessions(schedule, datetime(2025,11,30))

    def test_split_adjusted_prices_do_not_create_artificial_loss(self):
        snapshot = make_snapshot()
        # A split-adjusted constant economic value stays flat across a split.
        snapshot["prices"]["S00"] = {d: 50.0 for d in snapshot["sessions"]}
        row = next(r for r in calculate(snapshot)["ranked"] if r["symbol"] == "S00")
        self.assertEqual([row[f"r{h}"] for h in (21,63,126)], [0,0,0])
