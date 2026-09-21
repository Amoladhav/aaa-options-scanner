"""Append-only CRS projection over immutable catalog reports; no provider I/O.

Canonical means the last committed non-replay report for one profile/session/
method. It is a current workspace choice, not proof of historical availability.
Replays pin their original prior report and do not change this choice.
"""
from datetime import date, datetime
import json
import math

from .catalog import digest, encoded, identifier
from .core import CALCULATION_VERSION, DataError, calculation_method, normalize_symbol


def method_key(method=None):
    return digest(encoded({'version': CALCULATION_VERSION,
                           'method': calculation_method() if method is None else method}))


def validate_history(result, data, profile):
    """Validate the projection against the exact report bytes before publication."""
    try:
        meta = result['history_provenance']
        if (encoded(result) != data or result['profile'] != profile
                or profile not in ('synthetic', 'public')
                or meta['schema_version'] != 1
                or meta['calculation_version'] != CALCULATION_VERSION
                or method_key(result['method']) != method_key()
                or date.fromisoformat(result['as_of']).isoformat() != result['as_of']
                or datetime.fromisoformat(result['generated_at']).utcoffset() is None):
            raise ValueError
        for key in ('prior_artifact_id', 'replay_of'):
            if meta[key] is not None:
                identifier(meta[key])
        rows = result['combined']
        if not 1 <= len(rows) <= 60000 or len(rows) != result['universe_size']:
            raise ValueError
        seen = set()
        for row in rows:
            symbol = row['symbol']
            if (normalize_symbol(symbol) != symbol or symbol in seen
                    or row['group'] not in ('stock', 'etf')):
                raise ValueError
            seen.add(symbol)
            if row['crs_status'] == 'ranked':
                if type(row['rank']) is not int or row['rank'] < 1 or row['bias'] not in ('long', 'short', 'neutral'):
                    raise ValueError
                for key in ('score', 'percentile', 'r21', 'r63', 'r126'):
                    if type(row[key]) not in (int, float) or not math.isfinite(row[key]):
                        raise ValueError
                if not 0 <= row['percentile'] <= 1 or row['crs_exclusion_reason'] is not None:
                    raise ValueError
            elif (row['crs_status'] != 'excluded' or row['rank'] is not None
                  or row['score'] is not None or row['bias'] != 'unranked'
                  or not isinstance(row['crs_exclusion_reason'], str)):
                raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError):
        raise DataError('HISTORY_INVALID') from None


def register_history(db, run_id, artifact_id, result):
    """Called within the catalog publication transaction, never commit separately."""
    from .report_service import coverage
    meta = result['history_provenance']
    key = method_key(result['method'])
    prior = meta['prior_artifact_id']
    if prior:
        row = db.execute('SELECT * FROM crs_runs WHERE artifact_id=?', (prior,)).fetchone()
        if (row is None or row['profile'] != result['profile'] or row['method_key'] != key
                or row['price_session'] >= result['as_of']
                or row['price_session'] != result['previous_session']):
            raise DataError('HISTORY_INVALID')
    if meta['replay_of']:
        row = db.execute('SELECT * FROM crs_runs WHERE artifact_id=?', (meta['replay_of'],)).fetchone()
        if (row is None or row['profile'] != result['profile'] or row['method_key'] != key
                or row['price_session'] != result['as_of']):
            raise DataError('HISTORY_INVALID')
    db.execute('INSERT INTO crs_runs (run_id,artifact_id,profile,price_session,calculation_version,method_key,evaluated_at,prior_artifact_id,replay_of,coverage_json) VALUES (?,?,?,?,?,?,?,?,?,?)',
               (run_id, artifact_id, result['profile'], result['as_of'], CALCULATION_VERSION,
                key, result['generated_at'], prior, meta['replay_of'], encoded(coverage(result)).decode('utf-8')))
    for row in result['combined']:
        ranked = row['crs_status'] == 'ranked'
        db.execute('INSERT INTO crs_results VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                   (run_id, row['symbol'], row['group'], row['crs_status'], row['crs_exclusion_reason'],
                    row['rank'], row['score'], *(row.get(k) if ranked else None for k in ('percentile','r21','r63','r126')), row['bias']))
    if not meta['replay_of']:
        db.execute('INSERT INTO canonical_sessions VALUES (?,?,?,?) ON CONFLICT(profile,price_session,method_key) DO UPDATE SET artifact_id=excluded.artifact_id',
                   (result['profile'], result['as_of'], key, artifact_id))


class CRSHistory:
    def __init__(self, catalog):
        self.catalog = catalog

    def list(self, profile, *, limit=100):
        if profile not in ('synthetic', 'public') or type(limit) is not int or not 1 <= limit <= 1000:
            raise DataError('HISTORY_INVALID')
        with self.catalog.connection() as db:
            rows = db.execute('SELECT h.*,r.master_id,r.settings_id,r.code_revision,(c.artifact_id=h.artifact_id) AS canonical FROM crs_runs h JOIN runs r ON r.id=h.run_id LEFT JOIN canonical_sessions c ON c.profile=h.profile AND c.price_session=h.price_session AND c.method_key=h.method_key WHERE h.profile=? ORDER BY h.price_session DESC,h.sequence DESC LIMIT ?', (profile, limit)).fetchall()
        return [dict(row) for row in rows]

    def show(self, artifact_id):
        identifier(artifact_id)
        # Check authoritative file availability/hash before presenting SQL data.
        self.catalog.read(artifact_id, 'report')
        with self.catalog.connection() as db:
            head = db.execute('SELECT h.*,r.master_id,r.settings_id,r.code_revision FROM crs_runs h JOIN runs r ON r.id=h.run_id WHERE h.artifact_id=?', (artifact_id,)).fetchone()
            if head is None:
                raise DataError('HISTORY_NOT_RECORDED')
            rows = db.execute('SELECT * FROM crs_results WHERE run_id=? ORDER BY peer_group,rank,symbol', (head['run_id'],)).fetchall()
        return {'run': dict(head), 'rows': [dict(row) for row in rows]}

    def prior(self, snapshot):
        # Only sessions supplied in the snapshot and strictly before its cutoff.
        # This avoids same-day reruns, future sessions and calendar-day guesses.
        sessions = {d for d in snapshot['sessions'] if d < snapshot['as_of']}
        with self.catalog.connection() as db:
            rows = db.execute('SELECT price_session,artifact_id FROM canonical_sessions WHERE profile=? AND method_key=? AND price_session<? ORDER BY price_session DESC',
                              (snapshot['profile'], method_key(), snapshot['as_of']))
            selected = next((r['artifact_id'] for r in rows if r['price_session'] in sessions), None)
        return selected

    def previous(self, artifact_id, snapshot):
        if artifact_id is None:
            return None
        recorded = self.show(artifact_id)['run']
        if (recorded['profile'] != snapshot['profile'] or recorded['method_key'] != method_key()
                or recorded['price_session'] >= snapshot['as_of']
                or recorded['price_session'] not in snapshot['sessions']):
            raise DataError('HISTORY_INVALID')
        result = json.loads(self.catalog.read(artifact_id, 'report'))
        return {'as_of': result['as_of'], 'profile': result['profile'], 'method': result['method'],
                'rows': [{k: row[k] for k in ('symbol','group','rank','score','bias')} for row in result['ranked']]}

    def compare(self, left_id, right_id):
        left, right = self.show(left_id), self.show(right_id)
        if (left['run']['profile'] != right['run']['profile']
                or left['run']['method_key'] != right['run']['method_key']):
            raise DataError('HISTORY_COMPARISON_INCOMPATIBLE')
        before = {(r['peer_group'],r['symbol']): r for r in left['rows']}
        after = {(r['peer_group'],r['symbol']): r for r in right['rows']}
        changes = []
        for key in sorted(before.keys() | after.keys()):
            a, b = before.get(key), after.get(key)
            changes.append({'group':key[0], 'symbol':key[1],
                            'membership':'added' if a is None else 'departed' if b is None else 'retained',
                            'before_status':a['status'] if a else None, 'after_status':b['status'] if b else None,
                            'rank_change':a['rank']-b['rank'] if a and b and a['rank'] is not None and b['rank'] is not None else None})
        return {'left':left['run'], 'right':right['run'],
                'master_changed':left['run']['master_id'] != right['run']['master_id'], 'changes':changes}
