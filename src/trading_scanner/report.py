"""Local user-facing reports; provider data never enters agent-review summaries."""
import csv
from html import escape
import json
from pathlib import Path

FIELDS = ("group", "rank", "symbol", "company", "sector", "adjusted_close",
          "r21", "r63", "r126", "z21", "z63", "z126", "score", "percentile", "bias")


def csv_cell(value):
    # Spreadsheet formula protection applies to text, not numeric negative returns.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def write_csv(path: Path, rows: list[dict], fields) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows({k: csv_cell(v) for k, v in row.items()} for row in rows)


def write_reports(result: dict, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    write_csv(destination / "rankings.csv", result["ranked"], FIELDS)
    write_csv(destination / "excluded.csv", result["excluded"], ("symbol", "group", "company", "reason"))
    (destination / "results.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    head = "".join(f'<th><button type="button" data-col="{i}">{escape(f)}</button></th>'
                   for i, f in enumerate(FIELDS))
    body = []
    for row in result["ranked"]:
        cells = []
        for key in FIELDS:
            value = row[key]
            display = f"{value:.2%}" if key in {"r21", "r63", "r126", "percentile"} else f"{value:.4f}" if isinstance(value, float) else str(value)
            cells.append(f'<td data-value="{escape(str(value), quote=True)}">{escape(display)}</td>')
        body.append(f'<tr data-group="{row["group"]}" data-sector="{str(row["sector_etf"]).lower()}" data-bias="{row["bias"]}">' + "".join(cells) + "</tr>")
    excluded = "".join(f'<li>{escape(r["symbol"])}: {escape(r["reason"])}</li>' for r in result["excluded"])
    label = "SYNTHETIC DEMO — invented prices" if result["profile"] == "synthetic" else "PUBLIC DATA SNAPSHOT — check as-of date"
    html = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cross-sectional momentum</title><style>
body{font:15px system-ui,sans-serif;margin:24px;background:#101824;color:#e5edf5}h1{margin-bottom:8px}
.note{color:#acbfd0;max-width:1000px;line-height:1.6}select,input,button{font:inherit;background:#1e3043;color:inherit;border:1px solid #54718b;border-radius:5px;padding:7px}
label{display:inline-block;margin:8px 14px 12px 0}.table{overflow:auto;max-height:70vh}table{border-collapse:collapse;width:100%}
th{position:sticky;top:0;background:#101824}th button{width:100%;white-space:nowrap}td{border-bottom:1px solid #2b3c4f;padding:9px;white-space:nowrap;text-align:right}td:nth-child(-n+5){text-align:left}
tr[data-bias=long]{background:#123630}tr[data-bias=short]{background:#3b2431}a{color:#8dd7ff}
</style><h1>Cross-sectional momentum</h1>"""
    html += f'<p><strong>{label}</strong> · as of {escape(result["as_of"])} · {len(result["ranked"])} ranked / {result["universe_size"]} symbols</p>'
    html += f'<p class="note">Prices: {escape(result["price_source"])}. Calendar: {escape(result["calendar_source"])}.<br>Membership observed: {escape(result["membership_observed_at"])}. Stocks and ETFs are ranked separately. Sector ETF view retains ranks within all ETFs. ETF selection is a starter watchlist, not a verified options-volume top 50.<br>21/63/126-session adjusted returns → horizon z-scores → 50/25/25 weighted composite → final z-score. Top/bottom 10% are candidate labels, not orders or probabilities. No OTA enrichment yet. Snapshot prices are not executable quotes.</p>'
    html += '<p><a href="universe.csv">Master universe CSV</a> · <a href="rankings.csv">Rankings CSV</a> · <a href="excluded.csv">Exclusions CSV</a></p><label>View <select id="group"><option value="all">All groups</option><option value="stock">Stocks</option><option value="etf">ETFs</option><option value="sector">Sector ETFs</option></select></label><label>Bias <select id="bias"><option value="all">All</option><option>long</option><option>short</option><option>neutral</option></select></label><label>Search <input id="search" placeholder="Symbol or company"></label>'
    html += '<div class="table"><table><thead><tr>' + head + '</tr></thead><tbody>' + "".join(body) + '</tbody></table></div><details><summary>Excluded symbols</summary><ul>' + excluded + '</ul></details>'
    html += """<script>
const tbody=document.querySelector('tbody');
const group=document.querySelector('#group'),bias=document.querySelector('#bias'),search=document.querySelector('#search');
function filter(){for(const r of tbody.rows){r.hidden=!(
(group.value==='all'||r.dataset.group===group.value||(group.value==='sector'&&r.dataset.sector==='true'))&&
(bias.value==='all'||r.dataset.bias===bias.value)&&r.textContent.toLowerCase().includes(search.value.toLowerCase()));}}
for(const el of [group,bias,search])el.addEventListener('input',filter);
let last=-1,ascending=true;
document.querySelectorAll('th button').forEach(b=>b.addEventListener('click',()=>{
const col=Number(b.dataset.col);ascending=last===col?!ascending:true;last=col;
const numeric=[1,5,6,7,8,9,10,11,12,13].includes(col);
const rows=Array.from(tbody.rows);rows.sort((a,b)=>{const x=a.cells[col].dataset.value,y=b.cells[col].dataset.value;
return (numeric?Number(x)-Number(y):x.localeCompare(y))*(ascending?1:-1);});rows.forEach(r=>tbody.appendChild(r));}));
</script></html>"""
    (destination / "report.html").write_text(html, encoding="utf-8")
