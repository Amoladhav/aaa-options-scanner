"""Deterministic invented prices, never substituted for a failed real download."""
from datetime import date, timedelta
import math


def make_snapshot() -> dict:
    days, day = [], date(2025, 1, 2)
    while len(days) < 150:
        if day.weekday() < 5:
            days.append(day.isoformat())
        day += timedelta(days=1)
    universe, prices = [], {}
    for group, prefix in (("stock", "S"), ("etf", "E")):
        for i in range(30):
            symbol = f"{prefix}{i:02}"
            universe.append({"symbol": symbol, "group": group,
                             "company": f"Synthetic {symbol}", "sector": ("Technology", "Energy", "Health")[i % 3],
                             "sector_etf": group == "etf" and i < 11})
            prices[symbol] = {d: 100 * math.exp((i - 15) * .0003 * j + .005 * math.sin(j / 8 + i))
                              for j, d in enumerate(days)}
    return {"schema_version": 1, "profile": "synthetic", "as_of": days[-1],
            "membership_observed_at": days[-1], "price_source": "invented deterministic prices",
            "calendar_source": "synthetic weekdays; not an exchange calendar", "sessions": days,
            "universe": universe, "prices": prices}
