"""Lossless OTA row capture, descriptive profiling and versioned interpretation.

Only user-run fetch/replay reads provider data. No network or credentials here.
"""
from copy import deepcopy
import math
from .core import DataError, normalize_symbol
from .ota import FIELDS, COUNT_FIELDS, CODE_FIELDS


def raw_rows(payload, max_rows=600):
    rows = payload if isinstance(payload, list) else payload.get('results', {}).get('data') if isinstance(payload, dict) and isinstance(payload.get('results'), dict) else None
    if not isinstance(rows, list) or len(rows) > max_rows:
        raise DataError('OTA_ENVELOPE_UNSUPPORTED')
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get('values'), dict):
            raise DataError('OTA_SCHEMA_INVALID')
        symbol = normalize_symbol(row.get('symbol'))
        if symbol in seen:
            raise DataError('OTA_DUPLICATE_PAGE_SYMBOL')
        seen.add(symbol)
    return rows


def numeric(value):
    if type(value) not in (int, float, str) or isinstance(value, str) and (not value.strip() or len(value) > 128):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, OverflowError):
        return None


def profile_rows(rows):
    """Types partition present values; string/negative counters are subsets."""
    fields = {}
    for row in rows:
        for field, value in row['values'].items():
            stat = fields.setdefault(field, dict(present=0, missing=0, null=0, number=0,
                string=0, boolean=0, object=0, array=0, blank_strings=0,
                numeric_strings=0, other_strings=0, negative_numbers=0,
                negative_numeric_strings=0, minimum=None, maximum=None))
            stat['present'] += 1
            kind = {type(None):'null', int:'number', float:'number', str:'string', bool:'boolean', dict:'object', list:'array'}[type(value)]
            stat[kind] += 1
            number = numeric(value)
            if kind == 'string':
                stat['blank_strings' if not value.strip() else 'numeric_strings' if number is not None else 'other_strings'] += 1
            if number is not None:
                if number < 0:
                    stat['negative_numeric_strings' if kind == 'string' else 'negative_numbers'] += 1
                stat['minimum'] = number if stat['minimum'] is None else min(stat['minimum'], number)
                stat['maximum'] = number if stat['maximum'] is None else max(stat['maximum'], number)
    for stat in fields.values():
        stat['missing'] = len(rows) - stat['present']
    return {'schema_version': 1, 'rows': len(rows), 'scope': 'immediate values fields; nested objects/arrays retained as types',
            'numeric_range': 'finite numbers and numeric strings combined', 'fields': fields}


def normalize_snapshot(snapshot):
    """Raw remains immutable. Typed values and usability are distinct outputs."""
    if snapshot.get('representation') != 'ota_raw' or snapshot.get('acquisition_status') != 'completed_short_page':
        raise DataError('DASHBOARD_INPUT_INVALID')
    output = {k: deepcopy(v) for k, v in snapshot.items() if k != 'rows'}
    output.update(representation='ota_normalized', normalization_version=1, rows=[])
    raw_rows(snapshot['rows'], max_rows=60000)
    for raw in snapshot['rows']:
        values = raw['values']
        row = {'symbol': normalize_symbol(raw['symbol']), 'parsed_values': {}, 'field_status': {}}
        for field in FIELDS:
            value = values.get(field)
            number = numeric(value)
            status = 'missing' if field not in values else 'null' if value is None else 'blank' if isinstance(value, str) and not value.strip() else 'non_numeric' if number is None else 'numeric_string' if isinstance(value, str) else 'numeric'
            row['parsed_values'][field] = number
            usable = number
            if number is not None:
                if number < 0:
                    status, usable = 'negative_unusable', None
                elif field in (*COUNT_FIELDS, *CODE_FIELDS):
                    # Decimal avoids truncation/rounding of string count values.
                    from decimal import Decimal, InvalidOperation
                    try:
                        exact = Decimal(str(value).strip())
                        if exact > 2**53 - 1 or exact != exact.to_integral_value():
                            status, usable = 'invalid_count', None
                        else:
                            usable = int(exact)
                    except InvalidOperation:
                        status, usable = 'invalid_count', None
            row[field] = usable
            row['field_status'][field] = status
        output['rows'].append(row)
    return output


def write_processing(snapshot, destination):
    from .dashboard import atomic_json
    profile = profile_rows(snapshot['rows'])
    atomic_json(destination / 'field-profile.json', profile)
    if snapshot['acquisition_status'] == 'completed_short_page':
        atomic_json(destination / 'normalized.json', normalize_snapshot(snapshot))
    return profile



def profile_summary(profile):
    """Agent-review counts only: no ranges, samples or unknown field names."""
    counters = ('present','missing','null','number','string','boolean','object','array',
                'blank_strings','numeric_strings','other_strings','negative_numbers','negative_numeric_strings')
    return {'rows': profile['rows'], 'fields': {field: {key: profile['fields'][field][key] for key in counters}
            for field in FIELDS if field in profile['fields']}}


def run_process(root, args):
    """Replay captured data without tokens/network; retain each processing run."""
    from .dashboard import read_json, atomic_json
    from .progress import RunProgress
    from .cli import code_revision
    from .run_ids import new_run_id
    run_id, progress, code = new_run_id(), None, None
    profile = None
    try:
        progress = RunProgress(root / 'artifacts/logs', run_id, 'ota-process', 'ota', code_revision())
        progress.begin()
        progress.start('ota_profile')
        snapshot = read_json(args.input, limit=220_000_000)
        if not isinstance(snapshot, dict) or snapshot.get('representation') != 'ota_raw' or snapshot.get('acquisition_status') not in ('incomplete', 'completed_short_page'):
            raise DataError('OTA_PROCESS_INVALID')
        rows = snapshot.get('rows')
        if not isinstance(rows, list) or len(rows) > 60000 or any(not isinstance(r, dict) or not isinstance(r.get('values'), dict) for r in rows):
            raise DataError('OTA_PROCESS_INVALID')
        destination = root / 'artifacts/ota-processing' / run_id
        profile = write_processing(snapshot, destination)
        progress.finish(counts={'rows_profiled': len(rows)})
        print(f'Field profile: {destination / "field-profile.json"}')
        print('Incomplete capture: profiling only.' if snapshot['acquisition_status'] == 'incomplete' else f'Normalized data: {destination / "normalized.json"}')
    except (Exception, KeyboardInterrupt) as exc:
        if progress:
            progress.pause()
        code = 'RUN_CANCELLED' if isinstance(exc, KeyboardInterrupt) else 'OTA_PROCESS_INVALID'
        print(f'{code}: local processing stopped.')
    finally:
        if progress:
            try:
                progress.end(code)
                progress.close()
            except OSError:
                code = code or 'LOG_UNAVAILABLE'
    try:
        path = root / 'artifacts/agent-review' / f'{run_id}.json'
        report = {'schema_version':1, 'run_id':run_id, 'code_revision':code_revision(), 'profile':'ota',
                  'checks':[{'name':'ota_local_processing', 'status':'failed' if code else 'passed'}], 'error_code':code}
        if profile is not None:
            report['data_profile'] = profile_summary(profile)
        atomic_json(path, report)
        print(f'Agent review: {path}')
    except OSError:
        code = code or 'OTA_PROCESS_INVALID'
        print('OTA_PROCESS_INVALID: review output unavailable.')
    return 130 if code == 'RUN_CANCELLED' else 1 if code else 0
