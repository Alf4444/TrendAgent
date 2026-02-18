import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data/latest.json"
REPORT_FILE = ROOT / "build/daily.html"

def build_report():
    if not DATA_FILE.exists(): return
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows_html = ""
    for item in data:
        ytd = item.get("return_ytd", "0,00")
        # Farvekodning af ÅTD
        ytd_val = float(ytd.replace(",", "."))
        ytd_class = "pos" if ytd_val > 0 else "neg" if ytd_val < 0 else ""

        rows_html += f"""
        <tr>
            <td><strong>{item.get('name', item['isin'])}</strong><br><small>{item['isin']}</small></td>
            <td>{item.get('nav', 0):,.2f} {item.get('currency', '')}</td>
            <td class="{ytd_class}">{ytd}%</td>
            <td>{item.get('return_1w')}%</td>
            <td>{item.get('return_1m')}%</td>
            <td><span class="badge">OPSAMLER DATA</span></td>
            <td><a href="{item.get('url', '#')}" target="_blank">PDF ↗</a></td>
        </tr>
        """

    html_template = f"""
    <!doctype html>
    <html lang="da">
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, sans-serif; margin: 30px; background: #f0f2f5; color: #1c1e21; }}
            table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.08); }}
            th, td {{ padding: 15px; text-align: left; border-bottom: 1px solid #eee; }}
            th {{ background: #1a73e8; color: white; text-transform: uppercase; font-size: 12px; letter-spacing: 1px; }}
            .pos {{ color: #1e8e3e; font-weight: bold; }}
            .neg {{ color: #d93025; font-weight: bold; }}
            .badge {{ background: #e8f0fe; color: #1967d2; padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <h1>TrendAgent Dashboard</h1>
        <p>Sidst opdateret: {datetime.now().strftime('%d-%m-%Y %H:%M')}</p>
        <table>
            <thead>
                <tr><th>Fond</th><th>Kurs</th><th>ÅTD</th><th>1 Uge</th><th>1 Md</th><th>Trend (MA)</th><th>Link</th></tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
    </body>
    </html>
    """
    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_template, encoding="utf-8")

if __name__ == "__main__":
    build_report()
