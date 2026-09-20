"""Versioned report expressions and a pure structured editor; never execute text."""
from dataclasses import dataclass
from decimal import Context, Decimal, localcontext
import json
import re

from .core import DataError
from .report_selection import ColumnFilter, field_value, number

MAX_EXPRESSION_BYTES = 32768
MAX_DEPTH = 4  # Group levels, including the root.
MAX_LEAVES = 32
MAX_NODES = 64
NUMERIC_OPS = ('eq', 'ne', 'gt', 'ge', 'lt', 'le')

# Units are explicit semantic families, not inferred from a column's name or
# values. Raw fields only inherit an existing, documented OTA field contract.
UNITS = {
    **dict.fromkeys(('score', 'z21', 'z63', 'z126'), 'standardized score'),
    **dict.fromkeys(('r21', 'r63', 'r126'), 'return fraction'),
    'percentile': 'rank fraction', 'rank': 'rank position', 'rank_change': 'rank position',
    **dict.fromkeys(('meanIvPcnt', 'ivHi1YrPcnt', 'ivLow1YrPcnt'), 'OTA IV percentage points'),
    **dict.fromkeys(('totalOpenInterest', 'totalOptionsVolume'), 'option contracts'),
    'daysToEarnings': 'calendar days', 'avgVol30d': 'underlying shares',
    'tradier_underlying_average_volume': 'underlying shares',
    'adjusted_close': 'quote price', 'tradier_underlying_price': 'quote price',
    'tradier_atm_strike': 'quote price',
    **{f'tradier_{side}_{key}': unit for side in ('call', 'put') for key, unit in (
        ('strike', 'quote price'), ('bid', 'quote price'), ('ask', 'quote price'),
        ('spread', 'quote price'), ('spread_pct', 'bid-ask spread percentage points'),
        ('open_interest', 'option contracts'), ('volume', 'option contracts'))},
}
UNITS.update({'ota_raw.' + key: UNITS[key] for key in (
    'meanIvPcnt', 'ivHi1YrPcnt', 'ivLow1YrPcnt', 'totalOpenInterest',
    'totalOptionsVolume', 'daysToEarnings', 'avgVol30d')})

ERROR_MESSAGES = {
    'REPORT_EXPRESSION_INVALID': 'Check the rule fields, comparisons and values. No changes were applied.',
    'REPORT_EXPRESSION_LIMIT': 'Use at most 32 rules, 4 group levels and a compact filter. No changes were applied.',
    'REPORT_EXPRESSION_UNITS': 'Column comparisons need matching documented units. Use a value filter for fields without defined units.',
    'REPORT_EXPRESSION_FACTOR': 'The multiplier must be a finite number between -1000000 and 1000000 (at most 32 characters).',
    'REPORT_COLUMN_UNKNOWN': 'A selected field is not available in this saved report.',
    'REPORT_FILTER_INVALID': 'Check the filter values; numeric comparisons need numbers and presence checks need an empty value.',
}


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise DataError('REPORT_EXPRESSION_INVALID')
        result[key] = value
    return result


def _reject_constant(value):
    raise DataError('REPORT_EXPRESSION_INVALID')


def encode_document(document):
    text = json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(text.encode('utf-8')) > MAX_EXPRESSION_BYTES:
        raise DataError('REPORT_EXPRESSION_LIMIT')
    return text


def empty_document():
    return {'version': 1, 'root': {'type': 'all', 'rules': []}}


def decode_document(text):
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_EXPRESSION_BYTES:
        raise DataError('REPORT_EXPRESSION_LIMIT')
    try:
        document = json.loads(text, object_pairs_hook=_pairs, parse_constant=_reject_constant)
    except (ValueError, RecursionError):
        raise DataError('REPORT_EXPRESSION_INVALID') from None
    validate_structure(document)
    return document


def validate_structure(document):
    """Bound even incomplete editor drafts before traversal or rendering."""
    if (not isinstance(document, dict) or set(document) != {'version', 'root'}
            or type(document['version']) is not int or document['version'] != 1):
        raise DataError('REPORT_EXPRESSION_INVALID')
    counts = [0, 0]

    def visit(node, depth):
        counts[0] += 1
        if counts[0] > MAX_NODES or depth > MAX_DEPTH + 1:
            raise DataError('REPORT_EXPRESSION_LIMIT')
        if not isinstance(node, dict) or not isinstance(node.get('type'), str):
            raise DataError('REPORT_EXPRESSION_INVALID')
        kind = node['type']
        if kind in ('all', 'any'):
            if depth > MAX_DEPTH:
                raise DataError('REPORT_EXPRESSION_LIMIT')
            if set(node) != {'type', 'rules'} or not isinstance(node['rules'], list):
                raise DataError('REPORT_EXPRESSION_INVALID')
            for child in node['rules']:
                visit(child, depth + 1)
        else:
            counts[1] += 1
            if counts[1] > MAX_LEAVES:
                raise DataError('REPORT_EXPRESSION_LIMIT')
            keys = {'type', 'field', 'op', 'value'} if kind == 'literal' else {'type', 'field', 'op', 'other', 'factor'}
            if kind not in ('literal', 'column') or set(node) != keys:
                raise DataError('REPORT_EXPRESSION_INVALID')
            if any(not isinstance(value, str) or len(value) > (256 if key in ('field', 'other') else 200)
                   or any(0xD800 <= ord(char) <= 0xDFFF for char in value) for key, value in node.items()):
                raise DataError('REPORT_EXPRESSION_INVALID')
    visit(document['root'], 1)
    if document['root']['type'] not in ('all', 'any'):
        raise DataError('REPORT_EXPRESSION_INVALID')
    encode_document(document)


@dataclass(frozen=True)
class ColumnComparison:
    field: str
    op: str
    other: str
    factor: Decimal

    def matches(self, row):
        left, right = number(field_value(row, self.field)), number(field_value(row, self.other))
        if left is None or right is None:
            return False
        # The bounded source mantissa and factor fit exactly at this precision.
        # A private context prevents callers' Decimal settings changing results.
        with localcontext(Context(prec=256, Emin=-20000, Emax=20000)):
            right = right * self.factor
            return {'eq': left == right, 'ne': left != right, 'gt': left > right,
                    'ge': left >= right, 'lt': left < right, 'le': left <= right}[self.op]


@dataclass(frozen=True)
class RuleGroup:
    kind: str
    rules: tuple

    def matches(self, row):
        outcomes = (rule.matches(row) for rule in self.rules)
        return all(outcomes) if self.kind == 'all' else any(outcomes)


def compile_expression(text, columns=None):
    """Return immutable, validated nodes; call once before scanning rows."""
    document = decode_document(text)

    def field_checked(field):
        if not field:
            raise DataError('REPORT_EXPRESSION_INVALID')
        if columns is not None and field not in columns:
            raise DataError('REPORT_COLUMN_UNKNOWN')

    def visit(node, root=False):
        kind = node['type']
        if kind in ('all', 'any'):
            if not node['rules'] and not (root and kind == 'all'):
                raise DataError('REPORT_EXPRESSION_INVALID')
            return RuleGroup(kind, tuple(visit(child) for child in node['rules']))
        field_checked(node['field'])
        if kind == 'literal':
            return ColumnFilter(node['field'], node['op'], node['value'])
        field_checked(node['other'])
        if node['op'] not in NUMERIC_OPS:
            raise DataError('REPORT_EXPRESSION_INVALID')
        unit = UNITS.get(node['field'])
        if unit is None or UNITS.get(node['other']) != unit:
            raise DataError('REPORT_EXPRESSION_UNITS')
        factor = number(node['factor'])
        if factor is None or len(node['factor']) > 32 or not -1000000 <= factor <= 1000000:
            raise DataError('REPORT_EXPRESSION_FACTOR')
        return ColumnComparison(node['field'], node['op'], node['other'], factor)
    return visit(document['root'], root=True)


def expression_for_selection(selection):
    """Migrate old AND-only URLs, preserving their exact membership."""
    document = decode_document(selection.expression) if selection.expression else empty_document()
    rules = [{'type': 'literal', 'field': rule.field, 'op': rule.op, 'value': rule.value}
             for rule in selection.filters]
    if rules:
        root = document['root']
        if root['type'] == 'all':
            root['rules'] = rules + root['rules']
        else:
            document['root'] = {'type': 'all', 'rules': [*rules, root]}
    validate_structure(document)
    return encode_document(document)


def expression_summary(text):
    document = decode_document(text)
    def visit(node):
        if node['type'] in ('all', 'any'):
            join = ' AND ' if node['type'] == 'all' else ' OR '
            return '(' + join.join(visit(child) for child in node['rules']) + ')' if node['rules'] else 'All rows'
        operator = {'eq': '=', 'ne': '≠', 'gt': '>', 'ge': '≥', 'lt': '<', 'le': '≤'}.get(node['op'], node['op'])
        operand = json.dumps(node['value'], ensure_ascii=False) if node['type'] == 'literal' else f"{node['factor']} × {node['other']}"
        return f"{node['field']} {operator} {operand}".rstrip()
    return visit(document['root'])


def edit_expression(draft, values, action):
    """Update an uncommitted draft; evaluation only happens on explicit Apply.

    Paths index the supplied bounded tree, never filesystem paths. This service
    accepts plain mappings and can also support a later CLI/setup editor.
    """
    document = decode_document(draft)
    expected = set()

    def update(node, path):
        prefix = 'e.' + path + '.'
        keys = ('type',) if node['type'] in ('all', 'any') else ('type', 'field', 'op', 'value', 'other', 'factor')
        expected.update(prefix + key for key in keys)
        get = lambda key, default='': values.get(prefix + key, node.get(key, default))
        kind = get('type')
        if node['type'] in ('all', 'any'):
            if kind not in ('all', 'any'):
                raise DataError('REPORT_EXPRESSION_INVALID')
            return {'type': kind, 'rules': [update(child, f'{path}.{i}') for i, child in enumerate(node['rules'])]}
        if kind == 'literal':
            return {'type': kind, 'field': get('field'), 'op': get('op'), 'value': get('value')}
        if kind == 'column':
            return {'type': kind, 'field': get('field'), 'op': get('op'), 'other': get('other'), 'factor': get('factor', '1')}
        raise DataError('REPORT_EXPRESSION_INVALID')

    document['root'] = update(document['root'], 'r')
    if set(values) - expected:
        raise DataError('REPORT_EXPRESSION_INVALID')
    if action == 'clear':
        return encode_document(empty_document())
    if action != 'apply':
        match = re.fullmatch(r'(add_rule|add_group|remove):(r(?:\.[0-9]{1,2}){0,4})', action)
        if not match:
            raise DataError('REPORT_EXPRESSION_INVALID')
        operation, path = match.groups()
        node, parent, index = document['root'], None, None
        for part in path.split('.')[1:]:
            index = int(part)
            if node['type'] not in ('all', 'any') or index >= len(node['rules']):
                raise DataError('REPORT_EXPRESSION_INVALID')
            parent, node = node, node['rules'][index]
        if operation == 'remove':
            if parent is None:
                raise DataError('REPORT_EXPRESSION_INVALID')
            parent['rules'].pop(index)
        elif node['type'] not in ('all', 'any'):
            raise DataError('REPORT_EXPRESSION_INVALID')
        else:
            node['rules'].append({'type': 'literal', 'field': '', 'op': 'eq', 'value': ''}
                                 if operation == 'add_rule' else {'type': 'all', 'rules': []})
    validate_structure(document)
    return encode_document(document)
