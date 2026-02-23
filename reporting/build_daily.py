import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data/latest.json"
HISTORY_FILE = ROOT / "data/history.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
REPORT_FILE = ROOT / "build/daily.html"
README_FILE = ROOT / "README.md"

def get_moving_average(history_list, days):
    if len(history_list) < days: return None
    return sum(history_list[-days:]) / days

def build_report():
    if not DATA_FILE.exists(): return
    
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        latest_data = json.load(f)
    
    history = {}
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, "r") as f:
            history = json.load(f)

    portfolio = {}
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE, "r") as f:
            portfolio = json.load(f)

    timestamp = datetime.now().strftime('%d-%m-%Y %H:%M')
    readme_content = f"# 📈 TrendAgent Pro Dashboard\n**Opdateret:** {timestamp}\n\n"
    readme_content += "| Fond | Kurs | ÅTD | Trend | Status | Drawdown |\n| :--- | :--- | :--- | :--- | :--- | :--- |\n"

    rows_html = ""
    
    for item in latest_data:
        isin = item.get('isin')
        nav = item.get('nav', 0)
        ytd = item.get('return_ytd', '0,00')
        
        # Hent historik for MA beregninger
        isin_history = list(history.get(isin, {}).values())
        ma20 = get_moving_average(isin_history, 20)
        ma50 = get_moving_average(isin_history, 50)
        
        # Drawdown beregning (fra historikken vi har indtil nu)
        if isin_history:
            ath = max(isin_history)
            drawdown = ((nav - ath) / ath) * 100 if ath > 0 else 0
        else:
            drawdown = 0

        # Portfolio logik (Aktiv/Inaktiv)
        port_info = portfolio.get(isin, {"active": False})
        is_active = port_info.get("active", False)
        status_tag = "✅ EJER" if is_active else "👀 OVERVÅGER"
        
        # Trend State & Signals (Placeholder indtil mere data findes)
        trend_state = "DATA OPSAMLES"
        trend_icon = "⏳"
        
        if ma20 and ma50:
            if nav > ma20 and ma20 > ma50:
                trend_state = "STÆRK OP"
                trend_icon = "🚀"
            elif nav < ma20:
                trend_state = "SVAGHED"
                trend_icon = "⚠️"
        
        # Byg README række
        readme_content += f"| {item.get('name')[:30]} | {nav:,.2f} | {ytd}% | {trend_icon} {trend_state} | {status_tag} | {drawdown:.1f}% |\n"

        # Byg HTML række
        rows_html += f"""
        <tr class="{'active-row' if is_active else ''}">
            <td><strong>{item.get('name')}</strong><br><small>{isin}</small></td>
            <td style="font-family: monospace;">{nav:,.2f}</td>
            <td style="font-weight: bold;">{ytd}%</td>
            <td>{trend_icon} {trend_state}</td>
            <td>{status_tag}</td>
            <td style="color: red;">{drawdown:.1f}%</td>
        </tr>
        """

    # Gem README.md
    README_FILE.write_text(readme_content, encoding="utf-8")

    # Gem HTML
    html_template = f"""
    <!DOCTYPE html>
    <html lang="da">
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: sans-serif; margin: 30px; background: #f0f2f5; }}
            .card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #eee; }}
            th {{ background: #1a73e8; color: white; }}
            .active-row {{ background: #e7f3ff; border-left: 5px solid #1a73e8; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>TrendAgent Pro</h1>
            <p>Sidst opdateret: {timestamp}</p>
            <table>
                <thead>
                    <tr>
                        <th>Investering</th><th>Kurs</th><th>ÅTD</th><th>Trend Analyse</th><th>Status</th><th>Drawdown</th>
                    </tr>
                </thead>
                <tbody>{rows_html}</tbody>
            </table>
        </div>
    </body>
    </html>
    """
    REPORT_FILE.write_text(html_template, encoding="utf-8")
    print("Dashboard opgraderet med portefølje-logik og nye målepunkter!")

if __name__ == "__main__":
    build_report()
