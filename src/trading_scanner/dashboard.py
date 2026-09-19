"""Combined research report, deterministic joins and session-based rank history."""
from copy import deepcopy
from datetime import date, datetime, timezone
from html import escape
import json
import math
from pathlib import Path
import tempfile

from .core import DataError, calculate, normalize_symbol
from .ota import FIELDS as OTA_FIELDS, IV_FIELDS, normalize_metric
from .report import FIELDS as CRS_FIELDS, write_csv, write_reports

FILTER_DEFAULTS = {'schema_version': 1, 'min_open_interest': 10000,
                   'min_option_volume': 90000, 'min_spread_liquidity': 85,
                   'min_days_to_earnings': None, 'min_mean_iv': None,
                   'max_mean_iv': None, 'max_ota_age_hours': 36, 'max_price_age_days': 4}
EXTRA_FIELDS = ('price_status', 'ota_status', 'review_status', 'rank_change', 'history_status',
                'meanIvPcnt', 'ivHi1YrPcnt', 'ivLow1YrPcnt', 'ivGauge',
                'spreadLiquidityPcnt', 'totalOpenInterest', 'totalOptionsVolume',
                'daysToEarnings', 'avgVol30d', 'ota_field_status', *(field + '_status' for field in IV_FIELDS))


TRADIER_FIELDS = ('tradier_status', 'tradier_profile', 'tradier_retrieved_at',
                  'tradier_expiration', 'tradier_atm_strike', 'tradier_underlying_price',
                  'tradier_underlying_average_volume', 'tradier_average_volume_period',
                  *(f'tradier_{side}_{field}' for side in ('call', 'put') for field in
                    ('strike', 'bid', 'ask', 'spread', 'spread_pct', 'open_interest', 'volume',
                     'bid_date', 'ask_date', 'status', 'greeks_status', 'greeks')))


def attach_tradier(result, probes):
    """Join explicitly supplied derived snapshots, preserving source and quote status.

    Duplicate symbols are ambiguous: callers must choose a run instead of silently
    overwriting it. Production, sandbox and synthetic outputs cannot be mixed.
    """
    from .chain_spreads import number
    lookup, profiles = {}, set()
    for probe in probes:
        if not isinstance(probe, dict) or probe.get('schema_version') != 1 or probe.get('source') != 'tradier':
            raise DataError('DASHBOARD_INPUT_INVALID')
        profile = probe.get('profile')
        if result['profile'] == 'synthetic' or profile not in ('sandbox', 'production'):
            raise DataError('DASHBOARD_INPUT_INVALID')
        profiles.add(profile)
        symbol = normalize_symbol(probe['symbol'])
        stamp = datetime.fromisoformat(probe['retrieved_at'])
        strike = probe.get('atm_strike')
        if symbol in lookup or len(profiles) > 1 or stamp.tzinfo is None or not number(strike) or strike <= 0:
            raise DataError('DASHBOARD_INPUT_INVALID')
        date.fromisoformat(probe['expiration'])
        if probe.get('expiration_type') != 'standard':
            raise DataError('DASHBOARD_INPUT_INVALID')
        joined = {'tradier_status': 'supplied_freshness_unverified', 'tradier_profile': profile,
                  'tradier_retrieved_at': stamp.isoformat(), 'tradier_expiration': probe['expiration'] + '*',
                  'tradier_atm_strike': strike, 'tradier_underlying_price': probe.get('underlying_price'),
                  'tradier_underlying_average_volume': probe.get('underlying_average_volume'),
                  'tradier_average_volume_period': probe.get('underlying_average_volume_period')}
        for side in ('call', 'put'):
            leg = probe.get(side)
            if not isinstance(leg, dict) or leg.get('strike') != strike:
                raise DataError('DASHBOARD_INPUT_INVALID')
            for field in ('strike', 'bid', 'ask', 'spread', 'spread_pct', 'open_interest', 'volume',
                          'bid_date', 'ask_date', 'status', 'greeks_status', 'greeks'):
                value = leg.get(field)
                joined[f'tradier_{side}_{field}'] = json.dumps(value, sort_keys=True, allow_nan=False) if field == 'greeks' and value is not None else deepcopy(value)
        lookup[symbol] = joined
    for row in result['combined']:
        row.update({key: None for key in TRADIER_FIELDS})
        row['tradier_status'] = 'not_supplied'
        row.update(lookup.get(row['symbol'], {}))
    return result


def read_json(path, limit=30_000_000):
    from .ota_config import pairs
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise DataError('DASHBOARD_INPUT_INVALID')
    return json.loads(raw, object_pairs_hook=pairs)


def atomic_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', dir=path.parent, encoding='utf-8', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, indent=2, allow_nan=False)
            stream.write('\n')
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def filters_checked(filters):
    if not isinstance(filters, dict) or set(filters) != set(FILTER_DEFAULTS) or type(filters['schema_version']) is not int or filters['schema_version'] != 1:
        raise DataError('CANDIDATE_CONFIG_INVALID')
    for key, value in filters.items():
        if key == 'schema_version':
            continue
        if value is None and key not in ('max_ota_age_hours', 'max_price_age_days'):
            continue
        if type(value) not in (int, float) or not 0 <= value <= 1e15 or not math.isfinite(value):
            raise DataError('CANDIDATE_CONFIG_INVALID')
    if filters['min_mean_iv'] is not None and filters['max_mean_iv'] is not None and filters['min_mean_iv'] > filters['max_mean_iv']:
        raise DataError('CANDIDATE_CONFIG_INVALID')
    return deepcopy(filters)


def ota_checked(payload, profile):
    if isinstance(payload, dict) and payload.get('representation') == 'ota_raw':
        from .ota_pipeline import normalize_snapshot
        payload = normalize_snapshot(payload)
    if not isinstance(payload, dict) or payload.get('source') != ('synthetic' if profile == 'synthetic' else 'ota'):
        raise DataError('DASHBOARD_INPUT_INVALID')
    stamp = datetime.fromisoformat(payload['retrieved_at'])
    if stamp.tzinfo is None or not isinstance(payload.get('rows'), list) or len(payload['rows']) > 60000:
        raise DataError('DASHBOARD_INPUT_INVALID')
    coverage = payload.get('coverage')
    if coverage not in ('short_page_observed', 'empty_page_reached', 'single_page_only', 'synthetic'):
        raise DataError('DASHBOARD_INPUT_INVALID')
    rows, seen = [], set()
    for row in payload['rows']:
        symbol = normalize_symbol(row['symbol'])
        if symbol in seen:
            raise DataError('DASHBOARD_INPUT_INVALID')
        seen.add(symbol)
        metrics = {key: normalize_metric(row[key], key) if row.get(key) is not None else None for key in OTA_FIELDS}
        for field in IV_FIELDS:
            status = row.get(field + '_status')
            if status not in (None, 'negative_unusable'):
                raise DataError('DASHBOARD_INPUT_INVALID')
            if status == 'negative_unusable' or row.get(field) is not None and metrics[field] is None:
                if metrics[field] is not None:
                    raise DataError('DASHBOARD_INPUT_INVALID')
                metrics[field + '_status'] = 'negative_unusable'
        statuses = row.get('field_status', {})
        if not isinstance(statuses, dict) or any(k not in OTA_FIELDS or v not in ('missing','null','blank','non_numeric','numeric_string','numeric','negative_unusable','invalid_count') for k,v in statuses.items()):
            raise DataError('DASHBOARD_INPUT_INVALID')
        if statuses:
            metrics['field_status'] = dict(statuses)
        rows.append({'symbol': symbol, **metrics})
    # Persist only this allowlist, never arbitrary provider properties.
    return {'source': payload['source'], 'retrieved_at': stamp.isoformat(),
            'coverage': coverage, 'observation_timestamp': None,
            'methodology': 'unverified', 'rows': rows}


def combine(snapshot, ota, filters=None, *, now=None, previous=None):
    result = calculate(snapshot)
    filters = filters_checked(FILTER_DEFAULTS if filters is None else filters)
    ota = ota_checked(ota, result['profile'])
    now = now or datetime.now(timezone.utc)
    age_hours = (now - datetime.fromisoformat(ota['retrieved_at'])).total_seconds() / 3600
    timing = 'future' if age_hours < -0.1 else 'stale' if age_hours > filters['max_ota_age_hours'] else 'returned'
    price_age = (now.date() - date.fromisoformat(result['as_of'])).days
    price_status = 'future' if price_age < 0 else 'stale' if price_age > filters['max_price_age_days'] else 'within_age_limit'
    lookup = {r['symbol']: r for r in ota['rows']}
    previous_rows = {}
    history_ok = previous is not None and previous.get('profile') == result['profile'] and previous.get('as_of') in snapshot['sessions'][:-1] and previous.get('method') == json.loads(json.dumps(result['method']))
    if history_ok:
        previous_rows = {(r['group'], r['symbol']): r for r in previous['rows']}
    consecutive = history_ok and previous['as_of'] == snapshot['sessions'][-2]
    combined = []
    for row in result['ranked']:
        matched = lookup.get(row['symbol'])
        joined = {**row, **{key: matched.get(key) if matched else None for key in OTA_FIELDS},
                  **{field + '_status': matched.get(field + '_status') if matched else None for field in IV_FIELDS},
                  'ota_field_status': json.dumps(matched.get('field_status', {}), sort_keys=True) if matched else None,
                  'price_status': price_status,
                  'ota_status': timing if matched else 'not_returned_by_screener',
                  'rank_change': None, 'history_status': 'no_prior_session'}
        if history_ok:
            prior = previous_rows.get((row['group'], row['symbol']))
            joined['history_status'] = 'new_to_ranked_universe' if prior is None else 'previous_session' if consecutive else 'history_gap'
            if prior is not None:
                joined['rank_change'] = prior['rank'] - row['rank']
        checks = []
        for setting, metric, is_min in [('min_open_interest','totalOpenInterest',True),
                                      ('min_option_volume','totalOptionsVolume',True),
                                      ('min_spread_liquidity','spreadLiquidityPcnt',True),
                                      ('min_days_to_earnings','daysToEarnings',True),
                                      ('min_mean_iv','meanIvPcnt',True), ('max_mean_iv','meanIvPcnt',False)]:
            threshold, value = filters[setting], joined.get(metric)
            if threshold is not None:
                checks.append(None if value is None else value >= threshold if is_min else value <= threshold)
        joined['review_status'] = ('not_tail' if row['bias'] == 'neutral' else
                                   'unknown' if price_status != 'within_age_limit' or joined['ota_status'] != 'returned' or None in checks else
                                   'matches_config_unverified' if all(checks) else 'below_config')
        combined.append(joined)
    keys = {(r['group'], r['symbol']) for r in result['ranked']}
    result.update(combined=combined, ota_metadata={k: v for k, v in ota.items() if k != 'rows'},
                  filters=filters, generated_at=now.isoformat(), price_status=price_status,
                  previous_session=previous['as_of'] if history_ok else None,
                  departed=[r for key, r in previous_rows.items() if key not in keys])
    return result


def history_previous(directory, snapshot):
    directory.mkdir(parents=True, exist_ok=True)
    candidates = [p for p in directory.glob('????-??-??.json') if p.stem < snapshot['as_of']]
    if not candidates:
        return None
    path = max(candidates)
    prior = read_json(path)
    if not isinstance(prior, dict) or not isinstance(prior.get('rows'), list) or prior.get('as_of') != path.stem:
        raise DataError('HISTORY_INVALID')
    seen = set()
    if len(prior['rows']) > 60000:
        raise DataError('HISTORY_INVALID')
    for row in prior['rows']:
        if not isinstance(row, dict) or set(row) != {'symbol', 'group', 'rank', 'score', 'bias'} or type(row['rank']) is not int or row['rank'] < 1:
            raise DataError('HISTORY_INVALID')
        symbol = normalize_symbol(row['symbol'])
        key = (row['group'], symbol)
        if row['group'] not in ('stock', 'etf') or row['bias'] not in ('long', 'short', 'neutral') or key in seen or type(row['score']) not in (int, float) or not math.isfinite(row['score']):
            raise DataError('HISTORY_INVALID')
        seen.add(key)
    return prior


def save_history(directory, result):
    session = date.fromisoformat(result['as_of']).isoformat()
    atomic_json(directory / f'{session}.json', {'as_of': session, 'profile': result['profile'],
                'method': json.loads(json.dumps(result['method'])),
                'rows': [{key: r[key] for key in ('symbol','group','rank','score','bias')} for r in result['ranked']]})


def synthetic_ota(snapshot):
    return {'source': 'synthetic', 'retrieved_at': snapshot['as_of'] + 'T22:00:00+00:00',
            'coverage': 'synthetic', 'rows': [
                {'symbol': row['symbol'], 'meanIvPcnt': 20 + i, 'ivHi1YrPcnt': 100,
                 'ivLow1YrPcnt': 10, 'ivGauge': i % 7, 'spreadLiquidityPcnt': 90,
                 'totalOpenInterest': 20000, 'totalOptionsVolume': None if i % 7 == 0 else 100000,
                 'daysToEarnings': 30, 'optionable': 1}
                for i, row in enumerate(snapshot['universe']) if i % 5 != 0]}


def write_dashboard(result, destination):
    write_reports(result, destination)
    fields = (*CRS_FIELDS, *EXTRA_FIELDS, *TRADIER_FIELDS)
    write_csv(destination / 'combined.csv', result['combined'], fields)
    write_csv(destination / 'candidates.csv', [r for r in result['combined'] if r['review_status'] == 'matches_config_unverified'], fields)
    write_csv(destination / 'departed.csv', result['departed'], ('symbol','group','rank','score','bias'))
    labels = {'symbol':'Symbol', 'company':'Company', 'group':'Group', 'sector':'Sector', 'bias':'CRS bias',
              'rank':'Rank', 'score':'CRS score', 'percentile':'Percentile', 'rank_change':'Rank change ↑',
              'ota_field_status':'OTA field status', 'price_status':'Price age', 'ota_status':'OTA coverage', 'review_status':'Review', 'history_status':'History',
              'meanIvPcnt':'Mean IV %', 'ivHi1YrPcnt':'1y IV high %', 'ivLow1YrPcnt':'1y IV low %',
              'meanIvPcnt_status':'Mean IV status', 'ivHi1YrPcnt_status':'IV high status', 'ivLow1YrPcnt_status':'IV low status', 'ivGauge':'IV gauge', 'spreadLiquidityPcnt':'OTA liquidity', 'totalOpenInterest':'Open interest',
              'totalOptionsVolume':'Options volume', 'daysToEarnings':'Days to earnings', 'avgVol30d':'Underlying avg volume (OTA 30d)'}
    columns = ('symbol','company','group','rank','score','bias', *EXTRA_FIELDS, *TRADIER_FIELDS)
    labels.update({key: key.replace('tradier_', 'Tradier ').replace('_', ' ').title() for key in TRADIER_FIELDS})
    numeric = {'rank','score','rank_change', *OTA_FIELDS,
               *(key for key in TRADIER_FIELDS if key.endswith(('_strike', '_price', '_bid', '_ask', '_spread', '_spread_pct', '_open_interest', '_volume')))}
    th = ''.join(f'<th><button data-col="{i}" data-numeric="{str(k in numeric).lower()}">{escape(labels.get(k,k))}</button></th>' for i,k in enumerate(columns))
    body = []
    for row in result['combined']:
        cells = []
        for key in columns:
            value = row.get(key)
            shown = '—' if value is None else f'{value:,.2f}' if isinstance(value,float) else f'{value:,}' if isinstance(value,int) else str(value)
            cells.append(f'<td data-value="{escape(str(value) if value is not None else "", quote=True)}">{escape(shown)}</td>')
        body.append(f'<tr data-group="{row["group"]}" data-bias="{row["bias"]}" data-review="{row["review_status"]}">' + ''.join(cells) + '</tr>')
    matched = sum(r['ota_status'] == 'returned' for r in result['combined'])
    shortlist = sum(r['review_status'] == 'matches_config_unverified' for r in result['combined'])
    label = 'SYNTHETIC DEMO · invented prices and options' if result['profile'] == 'synthetic' else 'PUBLIC PRICES + OTA SCREENER'
    html = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Momentum + OTA dashboard</title><style>
:root{color-scheme:dark}body{margin:0;background:#0c1420;color:#e5eef8;font:15px system-ui,sans-serif}main{padding:28px;max-width:1800px;margin:auto}h1{font-size:32px;margin:10px 0}.eyebrow{color:#73d3c7;letter-spacing:.1em;font-size:12px}.muted{color:#a6b9cd;line-height:1.6}.cards{display:flex;gap:16px;flex-wrap:wrap;margin:24px 0}.card{background:#142337;border:1px solid #30445e;border-radius:12px;padding:18px;min-width:160px}.card b{font-size:30px;display:block}.toolbar{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0}input,select,button{background:#15283d;color:inherit;border:1px solid #41607e;border-radius:5px;padding:9px;font:inherit}a{color:#8edee0}.table{overflow:auto;max-height:65vh;border:1px solid #30445e;border-radius:10px}table{border-collapse:collapse;width:100%}th{position:sticky;top:0;background:#142337;white-space:nowrap}td{padding:12px;border-bottom:1px solid #24364d;white-space:nowrap}tr[data-review=matches_config_unverified]{background:#13352f}details{margin-top:20px}summary{cursor:pointer}button{cursor:pointer}
</style><main>'''
    html += f'<div class="eyebrow">{label}</div><h1>Momentum + options research</h1><p class="muted">Price session: {escape(result["as_of"])} · OTA retrieved: {escape(result["ota_metadata"]["retrieved_at"])}<br>Prior recorded session: {escape(result["previous_session"] or "none")}</p>'
    html += '<div class="cards">' + ''.join(f'<div class="card"><b>{n}</b>{caption}</div>' for n,caption in [(len(result['ranked']),'Ranked symbols'),(matched,'Freshly retrieved OTA matches'),(shortlist,'Tail rows matching config'),(len(result['excluded']),'Price exclusions')]) + '</div>'
    html += '<p class="muted">CRS ranks stocks and ETFs separately. OTA metrics do not change CRS scores. IV rank and IV percentile are not available here; provider mean IV and gauge retain their original meaning. Green rows match your numeric settings, not a validated trading signal. Quote time and metric methodology are unverified. Not returned means absent from the filtered screener, not zero liquidity.</p>'
    html += '<p class="muted">Tradier ATM quotes: explicitly supplied saved results; freshness unverified. * marks the selected standard monthly expiry. Bid, ask and spread are dollars per share; spread_pct is percent of midpoint. Call/put volume is current contract volume, not an average. Underlying average volume retains its provider period. Greeks retain provider values and update times; missing results are not zero.</p>'
    html += '<p><a href="combined.csv">Combined CSV</a> · <a href="candidates.csv">Review candidates CSV</a> · <a href="report.html">CRS calculation detail</a> · <a href="departed.csv">Departed symbols</a></p>'
    html += '<div class="toolbar"><input id="search" placeholder="Search symbol or company" aria-label="Search"><select id="group" aria-label="Group"><option value="all">All groups</option><option value="stock">Stocks</option><option value="etf">ETFs</option></select><select id="bias" aria-label="CRS bias"><option value="all">All CRS labels</option><option>long</option><option>short</option><option>neutral</option></select><select id="review" aria-label="Review status"><option value="all">All review statuses</option><option value="matches_config_unverified">Matches settings</option><option value="unknown">Unknown</option><option value="below_config">Below settings</option></select><span id="visible"></span></div>'
    html += '<div class="table"><table><thead><tr>' + th + '</tr></thead><tbody>' + ''.join(body) + '</tbody></table></div>'
    html += '<details><summary>Method, freshness and history</summary><p class="muted">21/63/126-session adjusted returns; 50/25/25 weights; cross-sectional z-scores. Price age is a calendar-day limit, not proof of the latest completed exchange session. Retrieval freshness is not quote freshness. Coverage: ' + escape(result['ota_metadata']['coverage']) + '. Positive rank change means improvement since the prior recorded session; history gaps are labeled. Universe changes can alter ranks without a price change. Daily history overwrites the same session rather than inventing additional streak days. No backtest or profitability claim.</p><pre>' + escape(json.dumps(result['filters'], indent=2)) + '</pre></details>'
    html += '''<script>
const body=document.querySelector('tbody');const selectors=['search','group','bias','review'].map(id=>document.getElementById(id));
function filter(){let n=0;for(const row of body.rows){row.hidden=!(row.textContent.toLowerCase().includes(selectors[0].value.toLowerCase())&&selectors.slice(1).every(el=>el.value==='all'||row.dataset[el.id]===el.value));if(!row.hidden)n++;}document.getElementById('visible').textContent=n+' visible';}selectors.forEach(el=>el.addEventListener('input',filter));filter();
let last=-1,ascending=true;document.querySelectorAll('th button').forEach(button=>button.addEventListener('click',()=>{const col=Number(button.dataset.col);ascending=col===last?!ascending:true;last=col;const numeric=button.dataset.numeric==='true';const rows=Array.from(body.rows);rows.sort((a,b)=>{const x=a.cells[col].dataset.value,y=b.cells[col].dataset.value;if(x==='')return y===''?0:1;if(y==='')return -1;return(numeric?Number(x)-Number(y):x.localeCompare(y))*(ascending?1:-1);});rows.forEach(row=>body.appendChild(row));}));
</script></main></html>'''
    (destination / 'dashboard.html').write_text(html, encoding='utf-8')
