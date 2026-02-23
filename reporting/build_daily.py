import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data/latest.json"
HISTORY_FILE = ROOT / "data/history.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
REPORT_FILE = ROOT / "build/daily.html"
README_FILE = ROOT / "README.md"

def get_ma(prices, window):
    if len(prices) < window: return None
    return sum(prices[-window:]) / window

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
    
    # Sortering: Aktive fonde øverst, derefter efter navn
    def sort_key(x):
        isin = x.get('isin')
        is_active = portfolio.get(isin, {}).get('active', False)
        return (not is_active, x.get('name', ''))

    sorted_data = sorted(latest_data, key=sort_key)

    # README Start
    readme_content = f"# 📈 TrendAgent Technical Dashboard\n**Analyse genereret:** {timestamp}\n\n"
    readme_content += "| Status | Fond | Kurs | ÅTD | Trend | Momentum | Drawdown |\n| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"

    rows_html = ""
    for item in sorted_data:
        isin = item.get('isin')
        nav = item.get('nav', 0)
        ytd = item.get('return_ytd', '0,00')
        
        # Hent historiske priser i kronologisk rækkefølge
        price_history = [v for k, v in sorted(history.get(isin, {}).items())]
        
        # Tekniske beregninger
        ma20 = get_ma(price_history, 20)
        ma50 = get_ma(price_history, 50)
        ma200 = get_ma(price_history, 200)
        
        # 1. Trend State (Langsigtet)
        trend_state = "⏳ Opsamler"
        if ma200:
            trend_state = "🐂 BULL" if nav > ma200 else "🐻 BEAR"
        elif ma50: # Backup hvis vi ikke har 200 dage endnu
            trend_state = "OP" if nav > ma50 else "NED"

        # 2. Momentum / Shift (MA20 vs MA50)
        momentum = "➡️ Neutral"
        if ma20 and ma50:
            if ma20 > ma50:
                momentum = "🔥 SHIFT OP" if price_history[-2] < ma50 else "🟢 Positiv"
            else:
                momentum = "❄️ SHIFT NED" if price_history[-2] > ma50 else "🔴 Negativ"

        # 3. Drawdown (Fald fra ATH i historikken)
        ath = max(price_history) if price_history else nav
        dd = ((nav - ath) / ath * 100) if ath > 0 else 0

        # Portfolio Status (Kun visuel markering)
        is_active = portfolio.get(isin, {}).get('active', False)
        status_icon = "⭐" if is_active else "🔍"

        # Formatering
        nav_str = "{:,.2f}".format(nav).replace(",", "X").replace(".", ",").replace("X", ".")
        
        # README Række
        readme_content += f"| {status_icon} | {item.get('name')[:30]} | {nav_str} | {ytd}% | {trend_state} | {momentum} | {dd:.1f}% |\n"
        
        # HTML Række
        row_class = "active-row" if is_active else ""
        rows_html += f"""
        <tr class="{row_class}">
            <td>{status_icon}</td>
            <td><strong>{item.get('name')}</strong></td>
            <td style="font-family: monospace;">{nav_str}</td>
            <td style="font-weight: bold; color: {'green' if float(ytd.replace(',','.')) >= 0 else 'red'}">{ytd}%</td>
            <td><span class="badge">{trend_state}</span></td>
            <td>{momentum}</td>
            <td style="color: #d93025;">{dd:.1f}%</td>
        </tr>
        """

    # Gem filer
    README_FILE.write_text(readme_content, encoding="utf-8")
    
    html_template = f"""
    <!DOCTYPE html>
    <html lang="da">
    <head>
        <meta charset="utf-8">
        <style>
            body {{ font-family: -apple-system, sans-serif; margin: 20px; background: #f8f9fa; color: #333; }}
            table {{ width: 100%; border-collapse: collapse; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }}
            th, td {{ padding: 12px 15px; text-align: left; border-bottom: 1px solid #eee; }}
            th {{ background: #1a73e8; color: white; font-size: 12px; text-transform: uppercase; }}
            .active-row {{ background: #f1f8ff; font-weight: 500; }}
            .badge {{ padding: 4px 8px; border-radius: 4px; background: #eee; font-size: 11px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <h1>TrendAgent Technical Analysis</h1>
        <p>Sidst opdateret: {timestamp} (PFA Data)</p>
        <table>
            <thead>
                <tr>
                    <th></th><th>Fond</th><th>NAV</th><th>ÅTD</th><th>Trend</th><th>Momentum (20/50)</th><th>Drawdown</th>
                </tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
    </body>
    </html>
    """
    REPORT_FILE.write_text(html_template, encoding="utf-8")
    print("Dashboard opdateret med tekniske signaler!")

if __name__ == "__main__":
    build_report()
