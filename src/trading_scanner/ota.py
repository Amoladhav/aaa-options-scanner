"""Pure OTA screener parsing from the owner-observed row schema.

No HTTP transport, credential handling or inferred financial definitions. Callers
must handle pagination and observation timestamps before publishing a snapshot.
"""
import math

from .core import DataError, normalize_symbol

# Keep vendor names: an IV level, categorical gauge and liquidity score cannot
# safely be substituted for IV rank, IV percentile or bid/ask spread.
PERCENT_FIELDS = ("meanIvPcnt", "ivHi1YrPcnt", "ivLow1YrPcnt", "spreadLiquidityPcnt")
COUNT_FIELDS = ("totalOpenInterest", "totalOptionsVolume")
CODE_FIELDS = ("ivGauge", "optionable")
FIELDS = (*PERCENT_FIELDS, *COUNT_FIELDS, *CODE_FIELDS)
SCHEMA_FIELDS = {*FIELDS, 'response', 'rows', 'row', 'symbol'}
SCHEMA_REASONS = {'invalid_json', 'not_array', 'too_many_rows', 'invalid_structure',
                  'invalid_symbol', 'duplicate_symbol', 'non_numeric', 'negative',
                  'non_finite', 'non_integer'}


class OtaSchemaError(DataError):
    """Fixed diagnostic vocabulary only; never retain provider values."""
    def __init__(self, field, reason):
        if field not in SCHEMA_FIELDS or reason not in SCHEMA_REASONS:
            raise ValueError('INVALID_DIAGNOSTIC')
        super().__init__('OTA_SCHEMA_INVALID')
        self.field, self.reason = field, reason


def parse_response(payload):
    """Support the reference adapter's results.data envelope and legacy arrays.

Do not recursively guess a list: other arrays may be metadata or errors.
Malformed recognized row containers remain errors, including on HTTP 200.
"""
    if isinstance(payload, list):
        return parse_rows(payload)
    if isinstance(payload, dict):
        results = payload.get('results')
        if isinstance(results, dict) and 'data' in results:
            return parse_rows(results['data'])
    raise DataError('OTA_ENVELOPE_UNSUPPORTED')


def parse_rows(rows):
    """Parse one explicit list of at most 100 rows; discard unneeded fields.

The response envelope is not established, so this function accepts only the
rows array. A short or empty page does not establish full-universe coverage.
Missing/null fields stay unknown; malformed supplied metrics reject the page.
"""
    def invalid(field, reason):
        raise OtaSchemaError(field, reason)

    if not isinstance(rows, list):
        invalid('rows', 'not_array')
    if len(rows) > 100:
        invalid('rows', 'too_many_rows')
    output, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("values"), dict):
            invalid('row', 'invalid_structure')
        try:
            symbol = normalize_symbol(row.get("symbol"))
        except (DataError, TypeError, AttributeError):
            invalid('symbol', 'invalid_symbol')
        if symbol in seen:
            invalid('symbol', 'duplicate_symbol')
        seen.add(symbol)
        values = row["values"]
        parsed = {"symbol": symbol}
        for field in FIELDS:
            value = values.get(field)
            if value is not None:
                if field in PERCENT_FIELDS:
                    # IV expressed in percent can exceed 100. The liquidity
                    # field's scale is unverified, so do not impose that ceiling.
                    if type(value) not in (int, float):
                        invalid(field, 'non_numeric')
                    if value < 0:
                        invalid(field, 'negative')
                    try:
                        finite = math.isfinite(value)
                    except OverflowError:
                        invalid(field, 'non_finite')
                    if not finite:
                        invalid(field, 'non_finite')
                elif type(value) is not int:
                    invalid(field, 'non_integer')
                elif value < 0:
                    invalid(field, 'negative')
            parsed[field] = value
        output.append(parsed)
    return output
