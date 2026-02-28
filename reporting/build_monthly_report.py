import json
from pathlib import Path
from datetime import datetime

# STIER
ROOT = Path(__file__).resolve().parent.parent
PORTFOLIO_FILE = ROOT / "config" / "portfolio.json"
LATEST_DATA = ROOT / "data" / "latest.json"
OUTPUT_FILE = ROOT / "docs" / "monthly_report.html"

def load_json(path):
    if not path.exists(): return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def generate_html():
    portfolio = load_json(PORTFOLIO_FILE)
    latest = load_json(LATEST_DATA)
    
    # Simple beregninger
    active_rows = ""
    for isin, info in portfolio.items():
        if not info.get('active', True): continue
        
        # Find nuværende kurs
        curr_price = 0
        for item in latest:
            if item.get('isin') == isin:
                curr_price = float(item.get('price', 0))
        
        pct = ((curr_price - info['buy_price']) / info['buy_price']) * 100
        color = "green" if pct >= 0 else "red"
        
        active_rows += f"""
        <tr>
            <td>{info['name']}</td>
            <td>{info['buy_date']}</td>
            <td>{info['buy_price']}</td>
            <td style="color: {color}; font-weight: bold;">{pct:.2f}%</td>
        </tr>
        """

    html_content = f"""
    <html>
    <head>
        <title>Monthly Deep Dive</title>
        <style>
            body {{ font-family: sans-serif; margin: 40px; background: #f4f7f6; }}
            table {{ width: 100%; border-collapse: collapse; background: white; }}
            th, td {{ padding: 12px; border: 1px solid #ddd; text-align: left; }}
            th {{ background: #2c3e50; color: white; }}
            h1 {{ color: #2c3e50; }}
        </style>
    </head>
    <body>
        <h1>📊 Monthly Deep Dive - {datetime.now().strftime('%B %Y')}</h1>
        <p>Benchmark: PFA Aktier (Under udvikling)</p>
        
        <h3>Aktive Positioner</h3>
        <table>
            <tr>
                <th>Fond</th>
                <th>Købsdato</th>
                <th>Købskurs</th>
                <th>Afkast %</th>
            </tr>
            {active_rows}
        </table>
    </body>
    </html>
    """
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)
    print("✅ Monthly report genereret i docs/monthly_report.html")

if __name__ == "__main__":
    generate_html()
