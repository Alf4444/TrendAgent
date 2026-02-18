# reporting/build_daily.py
import json, pathlib, datetime

ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "latest.json"
OUT = ROOT / "build" / "daily.html"

def dk_number(x):
    if x is None or x == "": return "N/A"
    try:
        return f"{float(x):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except: return "N/A"

def render_html(funds):
    today = datetime.date.today().isoformat()
    
    html = f"""<!doctype html>
<html lang="da">
<head>
    <meta charset="utf-8" />
    <title>TrendAgent – Rapport</title>
    <style>
        body {{ font-family: sans-serif; margin: 20px; color: #333; }}
        table {{ border-collapse: collapse; width: 100%; border: 1px solid #ddd; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f4f4f4; }}
        .pos {{ color: #28a745; font-weight: bold; }}
        .neg {{ color: #dc3545; font-weight: bold; }}
        .na {{ color: #999; font-style: italic; }}
        .badge {{ padding: 4px 8px; border-radius: 4px; font-size: 11px; background: #eee; }}
        a {{ color: #0066cc; text-decoration: none; }}
    </style>
</head>
<body>
    <h1>TrendAgent – Daglig status</h1>
    <p><small>Genereret: {today}</small></p>
    
    <table>
        <thead>
            <tr>
                <th>ISIN / PFA-ID</th>
                <th>NAV</th>
                <th>Dato</th>
                <th>Valuta</th>
                <th>Trend (MA)</th>
                <th>Dokument</th>
            </tr>
        </thead>
        <tbody>"""

    for f in funds:
        nav_val = dk_number(f.get("nav"))
        # Simpel farvekode logic til senere brug (1D/5D)
        change_class = "pos" if f.get("1d_change", 0) > 0 else "neg"
        
        html += f"""
            <tr>
                <td><strong>{f.get('isin')}</strong></td>
                <td>{nav_val}</td>
                <td class="{'na' if not f.get('nav_date') else ''}">{f.get('nav_date') or 'Mangler'}</td>
                <td>{f.get('currency') or '<span class="na">N/A</span>'}</td>
                <td><span class="badge">NEUTRAL</span></td>
                <td><a href="{f.get('url')}" target="_blank">Åbn PDF ↗</a></td>
            </tr>"""

    html += "</tbody></table></body></html>"
    return html

def main():
    if not DATA.exists():
        print("Ingen data fundet!"); return
    
    funds = json.loads(DATA.read_text(encoding="utf-8"))
    html_content = render_html(funds)
    
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html_content, encoding="utf-8")
    print(f"Rapport klar: {OUT}")

if __name__ == "__main__":
    main()
