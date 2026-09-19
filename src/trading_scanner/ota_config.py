"""Local screener payload -> versioned configuration. Never evaluates pasted code."""
import json
import math
from pathlib import Path
import re
import tempfile

from .core import DataError

MAX_INPUT = 200_000
TOKEN = re.compile(r'\s+|"(?:[^"\\\x00-\x1f]|\\["\\/bfnrt]|\\u[0-9a-fA-F]{4})*"|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|[A-Za-z_][A-Za-z_0-9]*|[{}\[\]:,]')
IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z_0-9]{0,63}\Z')
FILTER_KEYS = {
    'SELECT': {'valueChoices'}, 'SELECT_CODED': {'valueChoices'},
    'BOOLEAN': {'valueChoices'}, 'RANGE_INSIDE': {'valueMin', 'valueMax'},
    'RANGE_OUTSIDE': {'valueMin', 'valueMax'},
    'COMPARE': {'valueChoices', 'valueComparison'},
}


def fail(code='OTA_CONFIG_INVALID'):
    raise DataError(code)


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            fail()
        result[key] = value
    return result


def parse_config(text):
    """Accept JSON or DevTools-style unquoted keys, with double-quoted strings.

Abbreviated previews, executable expressions, comments and duplicate keys fail.
Only keys are repaired; values and active/inactive flags retain their meaning.
"""
    if not isinstance(text, str) or len(text) > MAX_INPUT:
        fail('OTA_CONFIG_TOO_LARGE')
    if '…' in text or '...' in text:
        fail('OTA_CONFIG_INCOMPLETE')
    tokens, position = [], 0
    for match in TOKEN.finditer(text):
        if match.start() != position:
            fail('OTA_CONFIG_SYNTAX')
        position = match.end()
        token = match.group()
        if not token.isspace():
            tokens.append(token)
    if position != len(text):
        fail('OTA_CONFIG_SYNTAX')
    normalized = []
    for i, token in enumerate(tokens):
        if IDENTIFIER.fullmatch(token) and i + 1 < len(tokens) and tokens[i + 1] == ':':
            token = json.dumps(token)
        normalized.append(token)
    try:
        rows = json.loads(' '.join(normalized), object_pairs_hook=pairs)
    except (ValueError, RecursionError):
        fail('OTA_CONFIG_SYNTAX')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        fail()
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            fail()
        field, kind = row.get('field'), row.get('valueFilter')
        if not isinstance(field, str) or not IDENTIFIER.fullmatch(field) or field in seen:
            fail()
        seen.add(field)
        if not isinstance(kind, str) or kind not in FILTER_KEYS:
            fail('OTA_CONFIG_UNSUPPORTED_FILTER')
        required = {'field', 'valueFilter'} | FILTER_KEYS[kind]
        optional = {'criteria'}
        if kind in ('RANGE_INSIDE', 'RANGE_OUTSIDE'):
            optional.add('valueChoices')
        if not required <= set(row) or set(row) - required - optional:
            fail()
        # OTA repeats the range operator in this optional field. Preserve it
        # for request replay, but reject a conflicting operator.
        if kind in ('RANGE_INSIDE', 'RANGE_OUTSIDE') and 'valueChoices' in row and row['valueChoices'] != kind:
            fail()
        if 'criteria' in row and not (type(row['criteria']) is bool or
                                      type(row['criteria']) is str and row['criteria'] in ('true', 'false')):
            fail()
        for key in ('valueMin', 'valueMax'):
            if key in row:
                value = row[key]
                if type(value) not in (int, float):
                    fail()
                try:
                    if not math.isfinite(value):
                        fail()
                except OverflowError:
                    fail()
        if 'valueMin' in row and row['valueMin'] > row['valueMax']:
            fail('OTA_CONFIG_RANGE_REVERSED')
        if 'valueChoices' in row:
            value = row['valueChoices']
            if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 32 for c in value):
                fail()
            if kind == 'BOOLEAN' and value not in ('Yes', 'No'):
                fail()
        if 'valueComparison' in row and (not isinstance(row['valueComparison'], str) or
                                        not IDENTIFIER.fullmatch(row['valueComparison'])):
            fail()
    return {'schema_version': 1, 'provider': 'ota', 'criteria': rows}


def save_config(config, destination: Path):
    """Validate again and atomically replace one configuration; never edit Python."""
    checked = parse_config(json.dumps(config['criteria'], allow_nan=False))
    if config != checked:
        fail()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=destination.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(checked, indent=2, allow_nan=False) + '\n')
        temporary.replace(destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
