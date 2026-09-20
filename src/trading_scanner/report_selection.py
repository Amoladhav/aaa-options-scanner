"""Pure, bounded saved-report views. No expressions, I/O or strategy changes."""
from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation
import json
import re

from .core import DataError
from .report import FIELDS
from .dashboard import EXTRA_FIELDS, TRADIER_FIELDS

MAX_RULES = 32
OPERATORS = {
    'eq': 'Equals', 'ne': 'Does not equal', 'contains': 'Contains text',
    'not_contains': 'Does not contain text', 'gt': '>', 'ge': '>=',
    'lt': '<', 'le': '<=', 'missing': 'Field absent', 'null': 'Explicit null',
    'blank': 'Blank text', 'present': 'Has a value',
}
DEFAULT_COLUMNS = ('symbol', 'company', 'group', 'score', 'percentile', 'ivGauge',
                   'crs_status', 'price_status', 'ota_status', 'tradier_status',
                   'tradier_atm_strike', 'tradier_call_bid', 'tradier_call_ask',
                   'tradier_put_bid', 'tradier_put_ask')
ABSENT = object()


def field_value(row, field):
    if field.startswith('ota_raw.'):
        values = row.get('ota_raw_values')
        # Display cells contain markers/JSON. Only retained originals can prove
        # null versus missing versus a source string literally saying "null".
        return values.get(field[8:], ABSENT) if isinstance(values, dict) else ABSENT
    return row.get(field, ABSENT)


def report_columns(result):
    """Known fields remain selectable even when every row lacks that value."""
    return tuple(dict.fromkeys((*FIELDS, 'ota_raw_status',
        *('ota_raw.' + field for field in result.get('ota_raw_fields', ())),
        *EXTRA_FIELDS, *TRADIER_FIELDS,
        *sorted({key for row in result['combined'] for key in row}))))


def number(value):
    # Decimal comparisons preserve numeric strings without modifying raw cells.
    # Bound parsing; never accept booleans, NaN, infinity or arbitrary expressions.
    if type(value) not in (int, float, str):
        return None
    text = str(value).strip()
    if len(text) > 128 or not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]{1,4})?', text):
        return None
    try:
        value = Decimal(text)
        return value if value.is_finite() else None
    except InvalidOperation:
        return None


def cell_text(value):
    if value is None:
        return '—'
    if isinstance(value, (dict, list, bool)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return str(value)


@dataclass(frozen=True)
class ColumnFilter:
    field: str
    op: str = 'contains'
    value: str = ''

    def __post_init__(self):
        if (not isinstance(self.field, str) or not 1 <= len(self.field) <= 256
                or self.op not in OPERATORS or not isinstance(self.value, str)
                or len(self.value) > 200
                or self.op in ('gt', 'ge', 'lt', 'le') and number(self.value) is None
                or self.op in ('missing', 'null', 'blank', 'present') and self.value):
            raise DataError('REPORT_FILTER_INVALID')

    def matches(self, row):
        actual = field_value(row, self.field)
        exists = actual is not ABSENT
        blank = isinstance(actual, str) and not actual.strip()
        if self.op == 'missing':
            return not exists
        if self.op == 'null':
            return exists and actual is None
        if self.op == 'blank':
            return blank
        if self.op == 'present':
            return exists and actual is not None and not blank
        # Unknowns never pass a comparison, including negative comparisons.
        if not exists or actual is None:
            return False
        a, b = number(actual), number(self.value)
        if self.op in ('gt', 'ge', 'lt', 'le'):
            if a is None or b is None:
                return False
            return {'gt': a > b, 'ge': a >= b, 'lt': a < b, 'le': a <= b}[self.op]
        text, query = cell_text(actual).casefold(), self.value.casefold()
        if self.op in ('eq', 'ne'):
            equal = a == b if a is not None and b is not None else text == query
            return equal if self.op == 'eq' else not equal
        return query in text if self.op == 'contains' else query not in text


@dataclass(frozen=True)
class Selection:
    search: str = ''
    group: str = 'all'
    tail: str = 'all'
    percent: float = 10
    sort: str = 'score'
    direction: str = 'desc'
    page: int = 1
    page_size: int = 25
    filters: tuple = ()
    columns: tuple = ()

    def __post_init__(self):
        if (not isinstance(self.search, str) or len(self.search) > 100
                or self.group not in ('all', 'stock', 'etf', 'sector')
                or self.tail not in ('all', 'top', 'bottom', 'both')
                or type(self.percent) not in (int, float) or not .1 <= self.percent <= 50
                or not isinstance(self.sort, str) or not 1 <= len(self.sort) <= 256
                or self.direction not in ('asc', 'desc')
                or type(self.page) is not int or not 1 <= self.page <= 100000
                or type(self.page_size) is not int or self.page_size not in (25, 50, 100, 250)
                or not isinstance(self.filters, tuple) or len(self.filters) > MAX_RULES
                or not all(isinstance(rule, ColumnFilter) for rule in self.filters)
                or not isinstance(self.columns, tuple) or len(self.columns) > 200
                or not all(isinstance(col, str) and 1 <= len(col) <= 256 for col in self.columns)
                or len(set(self.columns)) != len(self.columns)):
            raise DataError('REPORT_SELECTION_INVALID')

    @classmethod
    def from_mapping(cls, values):
        if set(values) - set(cls.__dataclass_fields__):
            raise DataError('REPORT_SELECTION_INVALID')
        options = dict(values)
        try:
            for key in ('page', 'page_size'):
                if key in options:
                    options[key] = int(options[key])
            if 'percent' in options:
                options['percent'] = float(options['percent'])
            return cls(**options)
        except (TypeError, ValueError):
            raise DataError('REPORT_SELECTION_INVALID') from None

    def query(self):
        values = asdict(self)
        values.pop('filters'); values.pop('columns')
        pairs = list(values.items())
        for rule in self.filters:
            pairs.extend((('field', rule.field), ('op', rule.op), ('value', rule.value)))
        pairs.extend(('column', col) for col in self.columns)
        return pairs


def select_rows(result, selection):
    columns = set(report_columns(result))
    if (selection.sort not in columns or set(selection.columns) - columns
            or any(rule.field not in columns for rule in selection.filters)):
        raise DataError('REPORT_COLUMN_UNKNOWN')
    rows = []
    for row in result['combined']:
        if selection.group != 'all' and not (row['group'] == selection.group or selection.group == 'sector' and row.get('sector_etf')):
            continue
        if selection.search.casefold() not in ' '.join(str(row.get(k, '')) for k in ('symbol', 'company', 'sector')).casefold():
            continue
        p, x = row.get('percentile'), selection.percent / 100
        if selection.tail != 'all' and (p is None or not ((selection.tail in ('top', 'both') and p >= 1-x) or (selection.tail in ('bottom', 'both') and p <= x))):
            continue
        if all(rule.matches(row) for rule in selection.filters):
            rows.append(row)
    # Keep numeric, text and missing buckets stable in either direction. Numeric
    # strings compare numerically; null/absent/blank stay last, ties by symbol.
    numeric, text, missing = [], [], []
    for row in sorted(rows, key=lambda r: r['symbol']):
        value = field_value(row, selection.sort)
        if value is ABSENT or value is None or isinstance(value, str) and not value.strip():
            missing.append(row)
        elif number(value) is not None:
            numeric.append(row)
        else:
            text.append(row)
    numeric.sort(key=lambda r: number(field_value(r, selection.sort)), reverse=selection.direction == 'desc')
    text.sort(key=lambda r: cell_text(field_value(r, selection.sort)).casefold(), reverse=selection.direction == 'desc')
    return numeric + text + missing


def watchlist_export(result, selection):
    """User-requested ###IVn syntax; preserve symbols, never guess exchanges."""
    sections, seen = {}, set()
    for row in select_rows(result, selection):
        symbol = row['symbol']
        if not isinstance(symbol, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,99}', symbol):
            raise DataError('WATCHLIST_SYMBOL_INVALID')
        if symbol in seen:
            continue
        seen.add(symbol)
        gauge = number(row.get('ivGauge'))
        gauge = int(gauge) if gauge is not None and 0 <= gauge <= 2**53-1 and gauge == gauge.to_integral_value() else None
        sections.setdefault(gauge, []).append(symbol)
    tokens = []
    for gauge in sorted(sections, key=lambda value: (value is None, value or 0)):
        tokens.extend(['###IV_UNKNOWN' if gauge is None else f'###IV{gauge}', *sections[gauge]])
    return (','.join(tokens) + ('\n' if tokens else '')).encode('utf-8')
