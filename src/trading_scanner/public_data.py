"""Explicit user-run public-data acquisition; never imported by offline commands.

No supplied Yahoo account credentials are needed. yfinance manages its own
anonymous session cookies; run this command yourself, never via agent automation.
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import math
from pathlib import Path

from .core import DataError, completed_sessions, normalize_universe

CONSTITUENTS_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


class ConstituentsParser(HTMLParser):
    """Read only the current constituents table, never the changes/history table."""
    def __init__(self):
        super().__init__()
        self.active = False
        self.cell = None
        self.row = []
        self.rows = []

    def handle_starttag(self, tag, attrs):
        if tag == "table" and dict(attrs).get("id") == "constituents":
            self.active = True
        if self.active and tag == "tr":
            self.row = []
        if self.active and tag in {"td", "th"}:
            self.cell = []

    def handle_data(self, data):
        if self.active and self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if self.active and tag in {"td", "th"} and self.cell is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
        if self.active and tag == "tr" and self.row:
            self.rows.append(self.row)
        if tag == "table":
            self.active = False


def parse_constituents(html: str, minimum: int = 450) -> list[dict]:
    parser = ConstituentsParser()
    parser.feed(html)
    if not parser.rows:
        raise DataError("CONSTITUENTS_SCHEMA_CHANGED")
    headers = parser.rows[0]
    required = ("Symbol", "Security", "GICS Sector")
    if not all(h in headers for h in required):
        raise DataError("CONSTITUENTS_SCHEMA_CHANGED")
    indexes = [headers.index(h) for h in required]
    result = []
    for row in parser.rows[1:]:
        if len(row) <= max(indexes):
            raise DataError("CONSTITUENTS_SCHEMA_CHANGED")
        symbol, company, sector = [row[i] for i in indexes]
        result.append({"symbol": symbol, "company": company, "sector": sector, "group": "stock"})
    result = normalize_universe(result)
    if not minimum <= len(result) <= 550:
        raise DataError("CONSTITUENTS_COUNT_INVALID")
    return result


def load_etfs(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as stream:
        result = []
        for row in csv.DictReader(stream):
            if row["sector_etf"] not in {"true", "false"}:
                raise DataError("INVALID_ETF_CONFIG")
            result.append({**row, "group": "etf", "sector_etf": row["sector_etf"] == "true"})
    return normalize_universe(result)


def series_prices(series, allowed_sessions: set[str]) -> dict:
    """Convert daily adjusted closes. Invalid values stay absent for exclusion."""
    result = {}
    for timestamp, raw in series.items():
        day = timestamp.date().isoformat()
        if day not in allowed_sessions:
            continue
        if day in result:
            raise DataError("DUPLICATE_PRICE_DATE")
        value = float(raw)
        if math.isfinite(value) and value > 0:
            result[day] = value
    return result


def fetch_snapshot(etf_path: Path, now: datetime | None = None, *, progress=None) -> dict:
    # Dependency imports and network are reachable only from the explicit command.
    if progress is not None:
        progress.start("dependencies")
    import urllib.request
    import exchange_calendars as calendars
    import yfinance as yf

    if progress is not None:
        progress.finish()
        progress.start("constituents")
    now = now or datetime.now(timezone.utc)
    request = urllib.request.Request(CONSTITUENTS_URL, headers={"User-Agent": "MomentumResearch/0.1 (personal research)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read(4_000_001)
    if len(body) > 4_000_000:
        raise DataError("CONSTITUENTS_RESPONSE_TOO_LARGE")
    universe = normalize_universe(parse_constituents(body.decode("utf-8")) + load_etfs(etf_path))
    if progress is not None:
        progress.finish(counts={"symbols_requested": len(universe)})
        progress.start("calendar")
    start = (now - timedelta(days=430)).date().isoformat()
    cal = calendars.get_calendar("XNYS", start=start, end=now.date().isoformat())
    schedule = [(stamp.date().isoformat(), row["close"].isoformat()) for stamp, row in cal.schedule.iterrows()]
    sessions = completed_sessions(schedule, now)
    if len(sessions) < 127:
        raise DataError("INSUFFICIENT_CALENDAR")
    cutoff = sessions[-1]
    allowed = set(sessions)
    if progress is not None:
        progress.finish()
    # yfinance's end is exclusive. Batching limits request bursts. Explicit
    # adjustment preserves split/dividend handling; no silent repair or filling.
    end = (datetime.fromisoformat(cutoff) + timedelta(days=1)).date().isoformat()
    prices = {}
    if progress is not None:
        progress.start("prices", total=(len(universe) + 39) // 40)
    for offset in range(0, len(universe), 40):
        symbols = [r["symbol"] for r in universe[offset:offset + 40]]
        frame = yf.download(symbols, start=start, end=end, interval="1d", auto_adjust=True,
                            back_adjust=False, repair=False, actions=False, threads=False,
                            progress=False, group_by="ticker", multi_level_index=True,
                            timeout=30, keepna=True, rounding=False, prepost=False)
        if frame is not None and not frame.empty:
            for symbol in symbols:
                if symbol in frame.columns.get_level_values(0):
                    prices[symbol] = series_prices(frame[symbol]["Close"], allowed)
        if progress is not None:
            # An empty response still completes an attempted batch, not a
            # successful data validation. Ranking reports missing histories.
            progress.advance(offset // 40 + 1, counts={"symbols_requested": min(offset + 40, len(universe)),
                                                      "symbols_received": sum(bool(p) for p in prices.values())})
    if progress is not None:
        progress.finish()
    return {"schema_version": 1, "profile": "public", "as_of": cutoff,
            "membership_observed_at": now.isoformat(), "price_source": "Yahoo Finance via yfinance; auto_adjust=True",
            "calendar_source": "exchange_calendars XNYS; one hour after session close",
            "constituents_source": CONSTITUENTS_URL,
            "constituents_attribution": "Wikipedia contributors; CC BY-SA; current membership only",
            "etf_selection": "11 sector ETFs and 50 starter ETFs; options-volume ranking not verified",
            "sessions": sessions, "universe": universe, "prices": prices}
