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
    
    # Sortering: Ejer-fonde først, derefter efter ÅTD afkast
    def sort_key(x):
        isin = x.get('isin')
        is_owned = portfolio.get(isin, {}).get('active', False)
        ytd = float(x.get('return_ytd', '0').replace(',', '.'))
        return (is_owned, ytd)

    sorted_data = sorted(latest_data, key=sort_key, reverse=True)

    # README Opbygning
    readme_content = f"# 📈 TrendAgent Pro\n**Opdateret:** {timestamp}\n\n"
    readme_content += "| Status | Fond | Kurs | ÅTD | Trend | Drawdown |\n| :--- | :--- | :--- | :--- | :--- | :--- |\n"

    rows_html = ""
    for item in sorted_data:
        isin = item.get('isin')
        nav = item.get('nav', 0)
        ytd = item.get('return_ytd', '0,00')
        
        # Hent prishistorik
        price_history = [v for k, v in sorted(history.get(isin, {}).items())]
        ma20 = get_ma(price_history, 20)
        ma50 = get_ma(price_history, 50)
        
        # Drawdown
        ath = max(price_history) if price_history else nav
        dd = ((nav - ath) / ath * 100) if ath > 0 else 0

        # Portfolio Logik - HER ER LØSNINGEN PÅ DIT SPØRGSMÅL
        port_info = portfolio.get(isin)
        if port_info:
            if port_info.get('active'):
                status_icon, status_text = "✅", "EJER"
                # Beregn personligt afkast hvis buy_price findes
                buy_p = port_info.get('buy_price', 0)
                p_ret = f" ({((nav-buy_p)/buy_p*100):+.1f}%)" if buy_p > 0 else ""
                status_text += p_ret
            else:
                status_icon, status_text = "📦", "SOLGT"
        else:
            status_icon, status_text = "👀", "OVERVÅGER"

        # Trend Logik
        trend_state = "Opsamler data..."
        if ma20:
            trend_state = "OP" if nav > ma20 else "NED"

        # Formatering til tabeller
        nav_str = "{:,.2f}".format(nav).replace(",", "X").replace(".", ",").replace("X", ".")
        
        readme_content += f"| {status_icon} | {item.get('name')[:30]} | {nav_str} | {ytd}% | {trend_state} | {dd:.1f}% |\n"
        
        rows_html += f"""
        <tr style="background: {'#e7f3ff' if status_icon == '✅' else 'white'}">
            <td>{status_icon} {status_text}</td>
            <td><strong>{item.get('name')}</strong></td>
            <td>{nav_str}</td>
            <td>{ytd}%</td>
            <td>{trend_state}</td>
            <td style="color: red">{dd:.1f}%</td>
        </tr>
        """

    # Gem filer
    README_FILE.write_text(readme_content, encoding="utf-8")
    
    html_template = f"<html><head><meta charset='utf-8'><style>body{{font-family:sans-serif;padding:20px;}}table{{width:100%;border-collapse:collapse;}}th,td{{padding:10px;border-bottom:1px solid #eee;}}th{{background:#eee;}}</style></head><body><h1>TrendAgent Pro</h1><table><thead><tr><th>Status</th><th>Fond</th><th>Kurs</th><th>ÅTD</th><th>Trend</th><th>Drawdown</th></tr></thead><tbody>{rows_html}</tbody></table></body></html>"
    REPORT_FILE.write_text(html_template, encoding="utf-8")

if __name__ == "__main__":
    build_report()
