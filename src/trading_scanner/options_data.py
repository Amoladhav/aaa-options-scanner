"""Offline normalized options summaries; no provider authentication or requests.

Values are descriptive only: provider definitions and aggregation remain unverified.
Session alignment is checked, not intraday freshness or historical availability.
"""
from copy import deepcopy
from datetime import date
import math

from .core import DataError, normalize_symbol

METRICS = ("iv_rank", "iv_percentile", "option_volume", "open_interest")
FIELDS = ("symbol", "options_status", "options_as_of", *METRICS)


def validate_options(payload, profile):
    """Return an allowlisted copy; reject unknown fields rather than persist them."""
    def invalid():
        raise DataError("INVALID_OPTIONS_INPUT")

    if not isinstance(payload, dict) or set(payload) != {"schema_version", "source", "methodology", "rows"}:
        invalid()
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        invalid()
    if payload["source"] not in ("synthetic", "user_supplied") or payload["methodology"] != "unverified":
        invalid()
    if profile not in ("synthetic", "public") or (payload["source"] == "synthetic") != (profile == "synthetic"):
        invalid()
    rows = payload["rows"]
    if not isinstance(rows, list) or len(rows) > 10000:
        invalid()
    cleaned, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"symbol", "as_of", *METRICS}:
            invalid()
        try:
            symbol = normalize_symbol(row["symbol"])
            session = date.fromisoformat(row["as_of"])
            if session.isoformat() != row["as_of"] or session.weekday() >= 5:
                invalid()
        except (ValueError, TypeError, AttributeError, DataError):
            invalid()
        if symbol in seen:
            invalid()
        seen.add(symbol)
        for key in METRICS:
            value = row[key]
            if value is None:
                continue
            if key in ("iv_rank", "iv_percentile"):
                if type(value) not in (int, float) or not 0 <= value <= 100 or not math.isfinite(value):
                    invalid()
            elif type(value) is not int or value < 0:
                invalid()
        cleaned.append({"symbol": symbol, "as_of": session.isoformat(), **{key: row[key] for key in METRICS}})
    return {"schema_version": 1, "source": payload["source"], "methodology": "unverified", "rows": cleaned}


def enrich(result, payload):
    """Keep momentum ranks intact; mismatched-session metrics are withheld."""
    payload = validate_options(payload, result["profile"])
    output = deepcopy(result)
    lookup = {row["symbol"]: row for row in payload["rows"]}
    rows = []
    for ranked in result["ranked"]:
        row = lookup.get(ranked["symbol"])
        status = "missing"
        if row is not None:
            status = "stale" if row["as_of"] < result["as_of"] else "future" if row["as_of"] > result["as_of"] else "aligned"
            if status == "aligned" and any(row[k] is None for k in METRICS):
                status = "partial"
        usable = status in ("aligned", "partial")
        rows.append({"symbol": ranked["symbol"], "options_status": status,
                     "options_as_of": row["as_of"] if row else None,
                     **{key: row[key] if usable else None for key in METRICS}})
    output["options"] = {"source": payload["source"], "methodology": "unverified", "rows": rows}
    return output


def synthetic_options(result):
    """Include partial and missing coverage to demonstrate honest reporting."""
    return {"schema_version": 1, "source": "synthetic", "methodology": "unverified",
            "rows": [{"symbol": row["symbol"], "as_of": result["as_of"],
                      "iv_rank": (i * 7) % 101, "iv_percentile": (i * 11) % 101,
                      "option_volume": None if i % 4 == 0 else i * 100,
                      "open_interest": i * 500} for i, row in enumerate(result["ranked"]) if i % 5 != 0]}
