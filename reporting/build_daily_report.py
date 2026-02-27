import json
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# Stier konfigureret til din arkitektur
ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data/latest.json"
HISTORY_FILE = ROOT / "data/history.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
TEMPLATE_FILE = ROOT / "templates/daily.html.j2"
REPORT_FILE = ROOT / "build/daily.html"
README_FILE = ROOT / "README.md"

def get_ma(prices, window):
    """Beregner MA baseret på tilgængelig historik. Robust overfor manglende data."""
    if not prices or len(prices) < 2: return None
    actual_window = min(len(prices), window)
    relevant = prices[-actual_window:]
    return sum(relevant) / len(relevant)

def build_report():
    if not DATA_FILE.exists():
        print("Fejl: latest.json ikke fundet.")
        return
    
    # Load data
    with open(DATA_FILE, "r", encoding="utf-8") as f: latest_data = json.load(f)
    with open(HISTORY_FILE, "r") as f: history = json.load(f)
    with open(PORTFOLIO_FILE, "r") as f: portfolio = json.load(f)

    timestamp = datetime.now().strftime('%d-%m-%Y %H:%M')
    processed_list = []

    for item in latest_data:
        isin = item.get('isin')
        nav = item.get('nav')
        if nav is None or isin is None: continue
        
        # Hent og sortér historik
        price_dict = history.get(isin, {})
        sorted_dates = sorted(price_dict.keys())
        price_history = [price_dict[d] for d in sorted_dates]
        
        # Tilføj nyeste NAV hvis den mangler i historikken
        if not price_history or price_history[-1] != nav:
            price_history.append(nav)

        # --- BEREGNINGER (SIGNALER & TREND) ---
        ma20 = get_ma(price_history, 20)
        ma50 = get_ma(price_history, 50)
        ma200 = get_ma(price_history, 200)
        
        # Distance til MA200
        dist_ma200 = ((nav - ma200) / ma200 * 100) if ma200 else 0
        
        # CROSS logik (20/50)
        cross_20_50 = "–"
        if ma20 and ma50 and len(price_history) > 1:
            p_ma20 = get_ma(price_history[:-1], 20)
            p_ma50 = get_ma(price_history[:-1], 50)
            if p_ma20 and p_ma50:
                if p_ma20 < p_ma50 and ma20 > ma50: cross_20_50 = "🚀 GOLDEN"
                elif p_ma20 > p_ma50 and ma20 < ma50: cross_20_50 = "💀 DEATH"

        # Signaler (Pris vs MA200)
        prev_nav = price_history[-2] if len(price_history) > 1 else nav
        day_chg = ((nav - prev_nav) / prev_nav * 100) if prev_nav else 0
        
        signal, has_signal = "–", 0
        if ma200:
            p_ma200 = get_ma(price_history[:-1], 200) or ma200
            if nav > ma200 and prev_nav <= p_ma200: signal, has_signal = "🚀 KØB", 1
            elif nav < ma200 and prev_nav >= p_ma200: signal, has_signal = "⚠️ SALG", 1

        # Drawdown & Portfolio
        ath = max(price_history) if price_history else nav
        drawdown = ((nav - ath) / ath * 100) if ath > 0 else 0
        
        p_info = portfolio.get(isin, {})
        is_active = p_info.get('active', False)
        buy_p = p_info.get('buy_price')
        total_return = ((nav - buy_p) / buy_p * 100) if is_active and buy_p else None

        processed_list.append({
            'isin': isin, 'name': item.get('name'),
            'day_chg': day_chg, 'dist_ma200': dist_ma200,
            'signal': signal, 'has_signal': has_signal,
            'is_active': is_active, 'drawdown': drawdown,
            'cross_20_50': cross_20_50, 'total_return': total_return,
            't_state': "BULL" if nav > (ma200 or 0) else "BEAR"
        })

    # --- SORTERING & OUTPUT ---
    # Top 3 / Bund 3 baseret på dagens performance
    outliers = sorted(processed_list, key=lambda x: x['day_chg'], reverse=True)
    top_3 = outliers[:3]
    bottom_3 = outliers[-3:][::-1]

    # README Opdatering (beholdt for robusthed)
    readme_content = f"# 📈 TrendAgent Fokus\n**Opdateret:** {timestamp}\n\n"
    readme_content += "| | Fond | Signal | Egen % | Trend | Afstand | Cross |\n| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
    for d in sorted(processed_list, key=lambda x: (not x['is_active'], x['signal'] == "–")):
        if d['is_active'] or d['has_signal']:
            ret = f"{d['total_return']:+.1f}%" if d['total_return'] is not None else "–"
            readme_content += f"| {'⭐' if d['is_active'] else '🔍'} | {d['name'][:20]} | {d['signal']} | {ret} | {d['t_state']} | {d['dist_ma200']:+.1f}% | {d['cross_20_50']} |\n"
    README_FILE.write_text(readme_content, encoding="utf-8")

    # Render HTML
    if TEMPLATE_FILE.exists():
        template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
        html_output = template.render(
            timestamp=timestamp, 
            funds=processed_list,
            top_3=top_3,
            bottom_3=bottom_3
        )
        REPORT_FILE.parent.mkdir(exist_ok=True)
        REPORT_FILE.write_text(html_output, encoding="utf-8")
    
    print(f"Daily Rapport færdig: {len(processed_list)} fonde analyseret.")

if __name__ == "__main__":
    build_report()
