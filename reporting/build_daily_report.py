import json
from pathlib import Path
from datetime import datetime
from jinja2 import Template

ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data/latest.json"
HISTORY_FILE = ROOT / "data/history.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
TEMPLATE_FILE = ROOT / "templates/daily.html.j2"
REPORT_FILE = ROOT / "build/daily.html"
README_FILE = ROOT / "README.md"

def get_ma(prices, window):
    clean_prices = [p for p in prices if p is not None]
    if not clean_prices or len(clean_prices) < window: return None
    return sum(clean_prices[-window:]) / len(clean_prices[-window:])

def build_report():
    if not DATA_FILE.exists(): return
    
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        latest_data = json.load(f)
    with open(HISTORY_FILE, "r") as f:
        history = json.load(f)
    with open(PORTFOLIO_FILE, "r") as f:
        portfolio = json.load(f)

    timestamp = datetime.now().strftime('%d-%m-%Y %H:%M')
    processed_list = []

    for item in latest_data:
        isin = item.get('isin')
        nav = item.get('nav')
        if nav is None: continue
        
        price_dict = history.get(isin, {}).copy()
        price_history = [v for k, v in sorted(price_dict.items())]
        if not price_history: price_history = [nav]

        # --- TEKNISKE INDIKATORER (Beholdt 1:1) ---
        ma20 = get_ma(price_history, 20)
        ma50 = get_ma(price_history, 50)
        ma200 = get_ma(price_history, 200)
        
        cross_20_50 = "–"
        if ma20 and ma50 and len(price_history) > 1:
            prev_ma20 = get_ma(price_history[:-1], 20)
            prev_ma50 = get_ma(price_history[:-1], 50)
            if prev_ma20 and prev_ma50:
                if prev_ma20 < prev_ma50 and ma20 > ma50: cross_20_50 = "🚀 GOLDEN"
                elif prev_ma20 > prev_ma50 and ma20 < ma50: cross_20_50 = "💀 DEATH"

        prev_nav = price_history[-2] if len(price_history) > 1 else nav
        day_chg = ((nav - prev_nav) / prev_nav * 100) if prev_nav else 0
        dist_ma200 = ((nav - ma200) / ma200 * 100) if ma200 else 0
        
        signal, has_signal = "–", 0
        if ma200 and len(price_history) > 1:
            curr_bull = nav > ma200
            prev_ma200 = get_ma(price_history[:-1], 200) or ma200
            if curr_bull and not (prev_nav > prev_ma200): 
                signal, has_signal = "🚀 KØB", 1
            elif not curr_bull and (prev_nav > prev_ma200): 
                signal, has_signal = "⚠️ SALG", 1

        # --- DRAWDOWN & PORTFOLIO ---
        ath = max(price_history) if price_history else nav
        drawdown = ((nav - ath) / ath * 100) if ath > 0 else 0
        
        p_info = portfolio.get(isin, {})
        is_active = p_info.get('active', False)
        buy_p = p_info.get('buy_price')
        total_return = ((nav - buy_p) / buy_p * 100) if is_active and buy_p else None

        processed_list.append({
            'isin': isin, 'name': item.get('name'), 'nav': nav,
            'day_chg': day_chg, 'dist_ma200': dist_ma200,
            'signal': signal, 'has_signal': has_signal,
            'is_active': is_active, 'drawdown': drawdown,
            'cross_20_50': cross_20_50, 'total_return': total_return,
            't_state': "BULL" if nav > (ma200 or 0) else "BEAR"
        })

    # --- SORTERING (Præcis som din gamle kode) ---
    processed_list.sort(key=lambda x: (not x['is_active'], not (x['has_signal'] and 'KØB' in x['signal']), -x['dist_ma200']))

    # --- README GENERERING (Vigtigt: Denne blev glemt i den korte version!) ---
    readme_content = f"# 📈 TrendAgent Fokus\n**Opdateret:** {timestamp}\n\n"
    readme_content += "| | Fond | Signal | Egen % | Trend | Afstand | Cross |\n| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
    for d in processed_list:
        if d['is_active'] or (d['has_signal'] and 'KØB' in d['signal']):
            ret_str = f"{d['total_return']:+.1f}%" if d['total_return'] is not None else "–"
            readme_content += f"| {'⭐' if d['is_active'] else '🔍'} | {d['name'][:20]} | {d['signal']} | {ret_str} | {d['t_state']} | {d['dist_ma200']:+.1f}% | {d['cross_20_50']} |\n"
    README_FILE.write_text(readme_content, encoding="utf-8")

    # --- HTML GENERERING (Via Jinja2 Template) ---
    template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
    html_output = template.render(timestamp=timestamp, funds=processed_list)
    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_output, encoding="utf-8")
    
    print(f"Daily Rapport færdig: {len(processed_list)} fonde. README og HTML opdateret.")

if __name__ == "__main__":
    build_report()
