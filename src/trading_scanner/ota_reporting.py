"""Pure OTA inventory report model and user-facing renderers, with no provider I/O."""
from dataclasses import dataclass
from datetime import datetime
from html import escape
import csv
import json

from .core import DataError
from .ota_pipeline import raw_rows, profile_rows
from .report import csv_cell

COLUMNS = ('sector', 'industry', 'last', 'volume', 'avgVol30d', 'marketcap',
           'meanIvPcnt', 'ivGauge', 'ivHi1YrPcnt', 'ivLow1YrPcnt',
           'spreadLiquidityPcnt', 'totalOpenInterest', 'totalOptionsVolume',
           'daysToEarnings', 'futureEarningsDate', 'sma_50', 'sma_200', 'optionable')


@dataclass(frozen=True)
class ReportOptions:
    console_rows: int = 20
    page_size: int = 100

    def __post_init__(self):
        if type(self.console_rows) is not int or not 0 <= self.console_rows <= 100:
            raise DataError('OTA_REPORT_INPUT_INVALID')
        if type(self.page_size) is not int or self.page_size not in (25, 50, 100, 250):
            raise DataError('OTA_REPORT_INPUT_INVALID')


def cell(values, field):
    """Explicit absence/type display; the raw source JSON remains authoritative."""
    if field not in values:
        return '[missing]'
    value = values[field]
    if isinstance(value, str):
        return value if value.strip() else json.dumps(value, ensure_ascii=True)
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':'))


def build_report(snapshot, source_sha256, *, generated_at, options=ReportOptions()):
    if (not isinstance(snapshot, dict) or snapshot.get('source') != 'ota'
            or snapshot.get('schema_version') != 2 or snapshot.get('representation') != 'ota_raw'
            or snapshot.get('acquisition_status') != 'completed_short_page'):
        raise DataError('OTA_REPORT_INPUT_INVALID')
    if type(snapshot.get('pages_received')) is not int or not 1 <= snapshot['pages_received'] <= 100:
        raise DataError('OTA_REPORT_INPUT_INVALID')
    rows = raw_rows(snapshot.get('rows'), max_rows=60000)
    stamp = snapshot.get('retrieved_at')
    if not isinstance(stamp, str) or datetime.fromisoformat(stamp).utcoffset() is None:
        raise DataError('OTA_REPORT_INPUT_INVALID')
    profile = profile_rows(rows)
    stats = profile['fields']
    fields = sorted(stats)
    sectors = {}
    for row in rows:
        sector = cell(row['values'], 'sector')
        sectors[sector] = sectors.get(sector, 0) + 1
    kinds = ('number','string','boolean','object','array')
    summary = {'rows':len(rows), 'fields':len(fields),
               'mixed_type_fields':sum(sum(stat[k] > 0 for k in kinds) > 1 for stat in stats.values()),
               'missing_cells':sum(stat['missing'] for stat in stats.values()),
               'null_cells':sum(stat['null'] for stat in stats.values()),
               'blank_strings':sum(stat['blank_strings'] for stat in stats.values()),
               'negative_values':sum(stat['negative_numbers'] + stat['negative_numeric_strings'] for stat in stats.values())}
    return {'schema_version':1, 'report_type':'ota_inventory',
            'profile':'synthetic' if snapshot.get('profile')=='synthetic' else 'ota',
            'generated_at':generated_at, 'source_sha256':source_sha256,
            'source_run_id':snapshot.get('run_id'), 'retrieved_at':stamp,
            'coverage':snapshot.get('coverage','unverified'), 'quote_freshness':'unverified',
            'pages_received':snapshot.get('pages_received'), 'summary':summary,
            'sectors':sectors, 'fields':fields, 'field_profile':profile,
            'absent_display_fields':[field for field in COLUMNS if field not in stats],
            'options':{'console_rows':options.console_rows,'page_size':options.page_size},
            'rows':rows}


def terminal(value, width):
    text = str(value)
    # External text must not control the terminal or create fake output lines.
    text = ''.join(c if c.isprintable() else ascii(c)[1:-1] for c in text)
    return text[:width].ljust(width)


def render_console(model):
    title = 'SYNTHETIC DEMO — invented data' if model['profile']=='synthetic' else 'OTA screener inventory'
    summary = model['summary']
    limit = model['options']['console_rows']
    out = [title, f"Rows: {summary['rows']} | Pages: {model['pages_received']} | Retrieved: {model['retrieved_at']}",
           'Short final page observed; full coverage and quote freshness remain unverified.',
           f"Fields: {summary['fields']} | Mixed types: {summary['mixed_type_fields']} | Nulls: {summary['null_cells']} | Blank strings: {summary['blank_strings']}"]
    fields = ('symbol','sector','avgVol30d','meanIvPcnt','totalOpenInterest','totalOptionsVolume')
    widths = (10,20,14,12,19,20)
    if limit:
        out += [' | '.join(terminal(f,w) for f,w in zip(fields,widths)), '-'*110]
        for row in model['rows'][:limit]:
            values = [row['symbol']] + [cell(row['values'],field) for field in fields[1:]]
            out.append(' | '.join(terminal(v,w) for v,w in zip(values,widths)))
    out.append(f"Preview: {min(limit,summary['rows'])}/{summary['rows']} rows. Files retain all rows; no CRS ranking applied.")
    return '\n'.join(out)


def write_rows_csv(model, path):
    with path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['symbol', *[csv_cell('values.'+f) for f in model['fields']]])
        for row in model['rows']:
            values = row['values']
            # Numeric source values remain numeric (including negatives); strings
            # get spreadsheet formula protection. JSON encodes nested structures.
            writer.writerow([csv_cell(row['symbol']), *[
                values[f] if f in values and type(values[f]) in (int,float) else csv_cell(cell(values,f))
                for f in model['fields']]])


def render_html(model):
    columns = ['symbol', *COLUMNS]
    data = {'columns':columns, 'rows':[[r['symbol'], *[cell(r['values'],f) for f in COLUMNS]] for r in model['rows']],
            'pageSize':model['options']['page_size']}
    encoded = json.dumps(data, ensure_ascii=True, allow_nan=False).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
    label = 'SYNTHETIC DEMO — invented data' if model['profile']=='synthetic' else 'OTA SCREENER · SAVED SNAPSHOT'
    cards = ''.join(f'<div class="card"><b>{value:,}</b><span>{escape(key.replace("_"," "))}</span></div>' for key,value in model['summary'].items())
    profile = ''.join('<tr><th>'+escape(field)+'</th>'+''.join('<td>'+escape(str(model['field_profile']['fields'][field][key]))+'</td>' for key in ('present','missing','null','number','string','blank_strings','negative_numbers','negative_numeric_strings'))+'</tr>' for field in model['fields'])
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OTA screener report</title>
<style>body{margin:0;background:#f3f6fa;color:#182b40;font:14px system-ui}main{margin:auto;padding:28px;max-width:1600px}h1{font-size:30px;margin:8px 0}.muted{color:#52667b}.cards{display:flex;flex-wrap:wrap;gap:12px;margin:22px 0}.card{background:white;border:1px solid #d9e2ec;border-radius:10px;padding:16px;min-width:125px}.card b{display:block;font-size:24px}.card span{color:#52667b}.toolbar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:18px 0}input,select,button{padding:8px;border:1px solid #b9c9d9;border-radius:5px;background:white;color:inherit}button{cursor:pointer}button:disabled{opacity:.4}.table{overflow:auto;background:white;border:1px solid #d9e2ec;max-height:68vh}table{border-collapse:collapse;width:100%;white-space:nowrap}th,td{padding:9px 12px;text-align:left;border-bottom:1px solid #e7edf3}thead{position:sticky;top:0;background:#eaf0f7}td{max-width:240px;overflow:hidden;text-overflow:ellipsis}tbody tr:nth-child(even){background:#f8fafc}a{color:#0867a5}details{margin:22px 0}code{overflow-wrap:anywhere}footer{margin-top:24px;color:#52667b}</style></head><body><main>
''' + f'<div class="muted">{label}</div><h1>Comprehensive OTA screener</h1><p class="muted">Retrieved: {escape(model["retrieved_at"])} · Source pages: {escape(str(model["pages_received"]))}</p>' + cards + '<p class="muted">Absent from every row: '+escape(', '.join(model['absent_display_fields']) or 'none')+'</p>'+ '''
<p>Every captured row is retained. This inventory does not apply CRS scores or replace the master universe. Build the combined dashboard to join these fields to master-list rankings.</p>
<p><a href="rows.csv">All rows CSV</a> · <a href="source.json">Original saved snapshot</a> · <a href="report.json">Report JSON</a> · <a href="field-profile.json">Field profile</a> · <a href="ota-symbols.txt">OTA symbols</a></p>
<div class="toolbar"><label>Search <input id="search" type="search" placeholder="Symbol, sector or industry"></label><label>Sector <select id="sector"><option value="">All sectors</option></select></label><label>Rows per page <select id="size"><option>25</option><option>50</option><option>100</option><option>250</option></select></label><button id="reset">Reset</button><span id="count" aria-live="polite"></span></div>
<div class="table"><table><thead><tr id="head"></tr></thead><tbody id="body"></tbody></table></div><div class="toolbar"><button id="prev">Previous</button><span id="page" aria-live="polite"></span><button id="next">Next</button></div>
<details><summary>Field-quality profile — all observed source fields</summary><p>Type counts describe source data, not eligibility. Negatives and mixed values are retained. Missing counts apply to fields observed somewhere in this snapshot; an entirely absent field is not part of that count.</p><div class="table"><table><thead><tr><th>Field</th><th>Present</th><th>Missing</th><th>Null</th><th>Number</th><th>String</th><th>Blank strings</th><th>Negative numbers</th><th>Negative numeric strings</th></tr></thead><tbody>''' + profile + '''</tbody></table></div></details>
<details><summary>Provenance and interpretation</summary><p>Full coverage and quote freshness remain unverified. A short final page is an observed stop condition, not provider-certified completeness. Mean IV, IV gauge and spread liquidity retain OTA's field meanings; they are not IV rank, IV percentile or ATM bid/ask spread. <code>[missing]</code> means absent; <code>null</code> is an explicit null; blank strings are quoted. JSON retains exact source types. Nested fields are available in the CSV and saved JSON. CSV prefixes potentially executable spreadsheet text with an apostrophe. No trade recommendations or synthetic fallback.</p>''' + f'<p>Source SHA256: <code>{escape(model["source_sha256"])}</code></p><p>Generated: {escape(model["generated_at"])}</p></details>' + '''
<footer>Local report. No external scripts, analytics or network requests. Click column headers to sort; search/filter changes reset pagination.</footer>
<script type="application/json" id="data">''' + encoded + r'''</script>
<script>
const data=JSON.parse(document.getElementById('data').textContent),el=id=>document.getElementById(id);
let page=0,sort=-1,direction=1;el('size').value=String(data.pageSize);
const sectors=[...new Set(data.rows.map(r=>r[1]))].sort();sectors.forEach((v,i)=>{const o=document.createElement('option');o.value=String(i);o.textContent=v;el('sector').appendChild(o)});
data.columns.forEach((name,i)=>{const th=document.createElement('th'),b=document.createElement('button');b.textContent=name;b.onclick=()=>{direction=sort===i?-direction:1;sort=i;page=0;draw()};th.appendChild(b);el('head').appendChild(th)});
function compare(a,b){const numeric=/^[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?$/i;if(numeric.test(a)&&numeric.test(b)&&Number.isFinite(Number(a))&&Number.isFinite(Number(b)))return Number(a)-Number(b);return a.localeCompare(b)}
function draw(){const q=el('search').value.toLowerCase(),sector=el('sector').value;let rows=data.rows.filter(r=>r.slice(0,3).some(v=>v.toLowerCase().includes(q))&&(sector===''||r[1]===sectors[Number(sector)]));if(sort>=0)rows.sort((a,b)=>direction*compare(a[sort],b[sort]));const size=Number(el('size').value),pages=Math.max(1,Math.ceil(rows.length/size));page=Math.min(page,pages-1);el('body').replaceChildren();rows.slice(page*size,(page+1)*size).forEach(r=>{const tr=document.createElement('tr');r.forEach(v=>{const td=document.createElement('td');td.textContent=v;td.title=v;tr.appendChild(td)});el('body').appendChild(tr)});el('count').textContent=rows.length+' / '+data.rows.length+' rows';el('page').textContent='Page '+(page+1)+' / '+pages;el('prev').disabled=page===0;el('next').disabled=page===pages-1}
['search','sector','size'].forEach(id=>el(id).addEventListener(id==='search'?'input':'change',()=>{page=0;draw()}));el('prev').onclick=()=>{page--;draw()};el('next').onclick=()=>{page++;draw()};el('reset').onclick=()=>{el('search').value='';el('sector').value='';sort=-1;direction=1;page=0;draw()};draw();
</script></main></body></html>'''
