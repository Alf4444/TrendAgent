import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data/latest.json"
HISTORY_FILE = ROOT / "data/history.json"
REPORT_FILE = ROOT / "build/daily.html"

def build_report():
    if not DATA_FILE.exists(): return
    
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Vi prøver at finde gårsdagens kurs i historikken for at regne Change %
    history = {}
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)

    rows_html = ""
    for item in data:
        name = item.get("name") or item["isin"]
        nav = item["nav"] or 0
        date = item["nav_date"] or "-"
        currency = item.get("currency", "-")
        
        # Simpel logik til Change % (hvis vi har mindst 2 datapunkter)
        change_html = '<span class="na">Ny</span>'
        isin = item["isin"]
        if isin in history and len(history[isin]) > 1:
            dates = sorted(history[isin].keys())
            last_date = dates[-1]
            prev_date = dates[-2]
            last_val = history[isin][last_date]
            prev_val = history[isin][prev_date]
            diff = ((last_val / prev_val) - 1) * 100
            color = "pos" if diff > 0 else "neg"
            change_html = f'<span class="{color}">{diff:+.2f}%</span>'

        rows_html += f"""
        <tr>
            <td><strong>{name}</strong><br><small style="color:#666">{item['isin']}</small></td>
            <td>{nav:,.2f}</td>
            <td>{change_html}</td>
            <td>{date}</td>
            <td>{currency}</td>
            <td><a href="{item['url']}" target="_blank">PDF ↗</a></td>
        </tr>
        """

    html_template = f"""
    <!doctype html>
    <html lang="da">
    <head>
        <meta charset="utf-8">
        <title>TrendAgent Rapport</title>
        <style>
            body {{ font-family: sans-serif; margin: 40px; background: #f9f9f9; }}
            table {{ border-collapse: collapse; width: 100%; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #eee; }}
            th {{ background: #2c3e50; color: white; }}
            .pos {{ color: #27ae60; font-weight: bold; }}
            .neg {{ color: #e74c3c; font-weight: bold; }}
            .na {{ color: #95a5a6; }}
        </style>
    </head>
    <body>
        <h1>TrendAgent – Daglig Rapport</h1>
        <p>Opdateret: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        <table>
            <thead>
                <tr>
                    <th>Fond Navn</th>
                    <th>NAV (Kurs)</th>
                    <th>Daglig %</th>
                    <th>Dato</th>
                    <th>Valuta</th>
                    <th>Link</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
    </body>
    </html>
    """
    
    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_template, encoding="utf-8")

if __name__ == "__main__":
    build_report()
