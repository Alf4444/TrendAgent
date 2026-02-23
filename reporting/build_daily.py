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
    clean_prices = [p for p in prices if p is not None]
    if len(clean_prices) < window: return None
    return sum(clean_prices[-window:]) / window

def format_dk(value):
    if value is None: return "N/A"
    try:
        return "{:,.2f}".format(value).replace(",", "X").replace(".", ",").replace("X", ".")
    except:
        return str(value)

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
    
    def sort_key(x):
        isin = x.get('isin')
        is_active = portfolio.get(isin, {}).get('active', False)
        return (not is_active, x.get('name', ''))

    sorted_data = sorted(latest_data, key=sort_key)

    # README Header
    readme_content = f"# 📈 TrendAgent Dashboard\n**Opdateret:** {timestamp}\n\n"
    readme_content += "| Stat | Signal | Fond | Kurs | 1D % | ÅTD | MA20/50 | Trend | Drawdown |\n| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"

    rows_html = ""
    for item in sorted_data:
        isin = item.get('isin')
        nav = item.get('nav')
        if nav is None: continue
        
        ytd_str = str(item.get('return_ytd', '0,00'))
        price_history = [v for k, v in sorted(history.get(isin, {}).items())]
        
        # Beregn alle MA-værdier
        ma20 = get_ma(price_history, 20)
        ma50 = get_ma(price_history, 50)
        ma200 = get_ma(price_history, 200)
        
        # 1D Change
        prev_nav = price_history[-2] if len(price_history) > 1 else nav
        day_change = ((nav - prev_nav) / prev_nav * 100) if prev_nav else 0
        
        # LOGIK FOR SIGNALER
        signal = "–"
        trend_state = "⏳ Data"
        trend_color = "#666"
        
        if ma200:
            current_bull = nav > ma200
            prev_ma200 = get_ma(price_history[:-1], 200) or ma200
            prev_bull = prev_nav > prev_ma200
            
            if current_bull and not prev_bull: signal = "🚀 KØB"
            elif not current_bull and prev_bull: signal = "⚠️ SALG"
            
            trend_state = "BULL" if current_bull else "BEAR"
            trend_color = "#28a745" if current_bull else "#d93025"
        
        # Drawdown
        ath = max(price_history) if price_history else nav
        dd = ((nav - ath) / ath * 100) if ath > 0 else 0

        is_active = portfolio.get(isin, {}).get('active', False)
        status_icon = "⭐" if is_active else "🔍"
        
        # Formatering
        chg_color = "#28a745" if day_change > 0 else "#d93025"
        ma_info = f"{format_dk(ma20)} / {format_dk(ma50)}"
        
        # HTML Række
        row_style = "style='background: #fff8e1; font-weight: bold;'" if is_active else ""
        rows_html += f"""
        <tr {row_style}>
            <td>{status_icon}</td>
            <td style="font-weight: bold; color: {'#1a73e8' if 'KØB' in signal else '#d93025'}">{signal}</td>
            <td>{item.get('name')[:40]}</td>
            <td>{format_dk(nav)}</td>
            <td style="color: {chg_color}">{day_change:+.2f}%</td>
            <td>{ytd_str}%</td>
            <td style="font-size: 0.85em; color: #666;">{ma_info}</td>
            <td style="color: {trend_color}; font-weight: bold;">{trend_state}</td>
            <td style="color: #d93025">{dd:.1f}%</td>
        </tr>
        """
        readme_content += f"| {status_icon} | {signal} | {item.get('name')[:20]} | {format_dk(nav)} | {day_change:+.2f}% | {ytd_str}% | {ma_info} | {trend_state} | {dd:.1f}% |\n"

    README_FILE.write_text(readme_content, encoding="utf-8")
    
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: sans-serif; margin: 10px; background: #f4f7f9; }}
            table {{ width: 100%; border-collapse: collapse; background: white; }}
            th, td {{ padding: 8px; border: 1px solid #eee; text-align: left; font-size: 12px; }}
            th {{ background: #1a73e8; color: white; position: sticky; top: 0; }}
            .bull {{ color: #28a745; font-weight: bold; }}
            .bear {{ color: #d93025; font-weight: bold; }}
        </style>
    </head>
    <body>
        <h2>TrendAgent Daily Dashboard</h2>
        <p>Opdateret: {timestamp}</p>
        <table>
            <thead>
                <tr><th></th><th>Signal</th><th>Fond</th><th>Kurs</th><th>1D %</th><th>ÅTD</th><th>MA20 / MA50</th><th>Trend</th><th>Drawdown</th></tr>
            </thead>
            <tbody>{rows_html}</tbody>
        </table>
    </body>
    </html>
    """
    REPORT_FILE.write_text(html_template, encoding="utf-8")
    print("Dashboard færdigbygget med ALT indhold!")

if __name__ == "__main__":
    build_report()
