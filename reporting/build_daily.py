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
    # Filtrer None-værdier fra hvis de findes i historikken
    clean_prices = [p for p in prices if p is not None]
    if len(clean_prices) < window: return None
    return sum(clean_prices[-window:]) / window

def build_report():
    if not DATA_FILE.exists(): 
        print("latest.json findes ikke!")
        return
        
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
    
    # Sortering: Aktive fonde øverst, derefter alfabetisk
    def sort_key(x):
        isin = x.get('isin')
        is_active = portfolio.get(isin, {}).get('active', False)
        return (not is_active, x.get('name', ''))

    sorted_data = sorted(latest_data, key=sort_key)

    # README Start
    readme_content = f"# 📈 TrendAgent Dashboard\n**Opdateret:** {timestamp}\n\n"
    readme_content += "| Status | Fond | Kurs | ÅTD | Trend | Momentum | Drawdown |\n| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"

    rows_html = ""
    for item in sorted_data:
        isin = item.get('isin')
        nav = item.get('nav')
        # Håndter ÅTD som tekst eller tal
        ytd_val = item.get('return_ytd', '0,00')
        ytd_str = str(ytd_val)
        
        # Hent historik og beregn indikatorer
        price_history = [v for k, v in sorted(history.get(isin, {}).items())]
        
        ma20 = get_ma(price_history, 20)
        ma50 = get_ma(price_history, 50)
        ma200 = get_ma(price_history, 200)
        
        # --- TEKNISKE INDIKATORER MED SIKKERHEDSNET ---
        
        # 1. Trend State (Langsigtet)
        trend_state = "⏳ Data..."
        if nav is not None:
            if ma200 is not None:
                trend_state = "🐂 BULL" if float(nav) > float(ma200) else "🐻 BEAR"
            elif ma50 is not None:
                trend_state = "📈 OP" if float(nav) > float(ma50) else "📉 NED"

        # 2. Momentum (Kortsigtet skæring)
        momentum = "➡️ Neutral"
        if ma20 is not None and ma50 is not None:
            if ma20 > ma50:
                # Tjek om det lige er sket (Shift)
                if len(price_history) > 2:
                    # Simpel check: var ma20 under ma50 i går?
                    momentum = "🟢 Positiv"
            else:
                momentum = "🔴 Negativ"

        # 3. Drawdown (Fald fra top)
        dd_str = "0.0%"
        if nav is not None and price_history:
            clean_hist = [p for p in price_history if p is not None]
            if clean_hist:
                ath = max(clean_hist)
                dd = ((float(nav) - float(ath)) / float(ath) * 100) if ath > 0 else 0
                dd_str = f"{dd:.1f}%"

        # Portfolio Status
        is_active = portfolio.get(isin, {}).get('active', False)
        status_icon = "⭐" if is_active else "🔍"

        # Formatering af Kurs
        nav_display = "{:,.2f}".format(nav).replace(",", "X").replace(".", ",").replace("X", ".") if nav else "N/A"
        
        # README Række
        readme_content += f"| {status_icon} | {item.get('name')[:30]} | {nav_display} | {ytd_str}% | {trend_state} | {momentum} | {dd_str} |\n"
        
        # HTML Række
        row_style = "style='background: #f1f8ff; font-weight: bold;'" if is_active else ""
        rows_html += f"""
        <tr {row_style}>
            <td>{status_icon}</td>
            <td>{item.get('name')}</td>
            <td>{nav_display}</td>
            <td>{ytd_str}%</td>
            <td>{trend_state}</td>
            <td>{momentum}</td>
            <td style="color: #d93025">{dd_str}</td>
        </tr>
        """

    # Gem README.md
    README_FILE.write_text(readme_content, encoding="utf-8")
    
    # Gem daily.html
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: sans-serif; margin: 20px; background: #f4f7f9; }}
            table {{ width: 100%; border-collapse: collapse; background: white; }}
            th, td {{ padding: 12px; border: 1px solid #eee; text-align: left; }}
            th {{ background: #1a73e8; color: white; }}
            tr:hover {{ background: #f9f9f9; }}
        </style>
    </head>
    <body>
        <h1>TrendAgent - Teknisk Oversigt</h1>
        <p>Opdateret: {timestamp}</p>
        <table>
            <thead>
                <tr><th></th><th>Fond</th><th>Kurs</th><th>ÅTD</th><th>Trend</th><th>Momentum</th><th>Drawdown</th></tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
    </body>
    </html>
    """
    REPORT_FILE.write_text(html_template, encoding="utf-8")
    print("Dashboard færdigbygget uden fejl!")

if __name__ == "__main__":
    build_report()
