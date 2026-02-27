import json
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# ==========================================
# KONFIGURATION & ROBUSTE STIER
# ==========================================
ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data/latest.json"
HISTORY_FILE = ROOT / "data/history.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
TEMPLATE_FILE = ROOT / "templates/daily.html.j2"
REPORT_FILE = ROOT / "build/daily.html"
README_FILE = ROOT / "README.md"

def get_ma(prices, window):
    """Beregner glidende gennemsnit (MA) baseret på tilgængelig historik."""
    if not prices or len(prices) < 2:
        return None
    actual_window = min(len(prices), window)
    relevant_prices = prices[-actual_window:]
    return sum(relevant_prices) / len(relevant_prices)

def build_report():
    # Sikkerhedstjek: Findes de nødvendige filer?
    if not DATA_FILE.exists():
        print(f"FEJL: {DATA_FILE} mangler.")
        return

    # 1. HENT DATA
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            latest_data = json.load(f)
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)
    except Exception as e:
        print(f"Fejl ved indlæsning af data: {e}")
        return

    timestamp = datetime.now().strftime('%d-%m-%Y %H:%M')
    processed_list = []

    # 2. BEHANDL HVER FOND
    for item in latest_data:
        isin = item.get('isin')
        nav = item.get('nav')
        if nav is None or isin is None:
            continue
        
        # Hent historik og sortér efter dato for at sikre korrekt rækkefølge
        price_dict = history.get(isin, {})
        sorted_dates = sorted(price_dict.keys())
        price_history = [price_dict[d] for d in sorted_dates]
        
        # Sikr at dagens NAV er med i beregningsgrundlaget
        if not price_history or price_history[-1] != nav:
            price_history.append(nav)

        # --- TEKNISKE BEREGNINGER ---
        ma20 = get_ma(price_history, 20)
        ma50 = get_ma(price_history, 50)
        ma200 = get_ma(price_history, 200)
        
        # Afstand til MA200 (Risiko-indikator)
        dist_ma200 = ((nav - ma200) / ma200 * 100) if ma200 else 0
        
        # CROSS logik (Tjekker om MA20 krydser MA50 præcis i dag)
        cross_20_50 = "–"
        if ma20 and ma50 and len(price_history) > 2:
            prev_ma20 = get_ma(price_history[:-1], 20)
            prev_ma50 = get_ma(price_history[:-1], 50)
            if prev_ma20 and prev_ma50:
                if prev_ma20 <= prev_ma50 and ma20 > ma50:
                    cross_20_50 = "🚀 GOLDEN"
                elif prev_ma20 >= prev_ma50 and ma20 < ma50:
                    cross_20_50 = "💀 DEATH"

        # Signal logik (Pris vs MA200)
        prev_nav = price_history[-2] if len(price_history) > 1 else nav
        day_chg = ((nav - prev_nav) / prev_nav * 100) if prev_nav else 0
        
        signal, has_signal = "–", 0
        if ma200:
            if nav > ma200 and prev_nav <= ma200:
                signal, has_signal = "🚀 KØB", 1
            elif nav < ma200 and prev_nav >= ma200:
                signal, has_signal = "⚠️ SALG", 1

        # Drawdown (Fald fra All-Time High i robotten)
        ath = max(price_history) if price_history else nav
        drawdown = ((nav - ath) / ath * 100) if ath > 0 else 0
        
        # Portfolio status & Stop-Loss Logik
        p_info = portfolio.get(isin, {})
        is_active = p_info.get('active', False)
        buy_p = p_info.get('buy_price')
        total_return = ((nav - buy_p) / buy_p * 100) if is_active and buy_p else None
        
        # Stop-loss flag: Aktiveres ved drawdown <= -10% eller egen retur <= -8%
        stop_alert = False
        if drawdown <= -10.0 or (is_active and total_return and total_return <= -8.0):
            stop_alert = True

        processed_list.append({
            'isin': isin, 
            'name': item.get('name'),
            'day_chg': day_chg, 
            'dist_ma200': dist_ma200,
            'signal': signal, 
            'has_signal': has_signal,
            'is_active': is_active, 
            'drawdown': drawdown,
            'cross_20_50': cross_20_50, 
            'total_return': total_return,
            'stop_alert': stop_alert,
            't_state': "BULL" if nav > (ma200 or 0) else "BEAR"
        })

    # 3. SORTERING (Eksplicit og robust)
    # Sorterer: Aktive (⭐) -> Signaler (KØB/SALG) -> Alfabetisk
    processed_list.sort(key=lambda x: (
        not x['is_active'],    
        x['signal'] == "–",     
        x['name']               
    ))

    # Top/Bund Outliers (bruges til Cards i HTML)
    outliers = sorted(processed_list, key=lambda x: x['day_chg'], reverse=True)
    top_3 = outliers[:3]
    bottom_3 = outliers[-3:][::-1]

    # 4. OPDATER README.MD
    readme_content = f"# 📈 TrendAgent Fokus\n**Opdateret:** {timestamp}\n\n"
    readme_content += "| | Fond | Signal | Egen % | Trend | Afstand | Cross |\n| :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
    for d in processed_list:
        if d['is_active'] or d['has_signal']:
            ret = f"{d['total_return']:+.1f}%" if d['total_return'] is not None else "–"
            alert_prefix = "⚠️ " if d.get('stop_alert') else ""
            readme_content += f"| {'⭐' if d['is_active'] else '🔍'} | {alert_prefix}{d['name'][:25]} | {d['signal']} | {ret} | {d['t_state']} | {d['dist_ma200']:+.1f}% | {d['cross_20_50']} |\n"
    
    try:
        README_FILE.write_text(readme_content, encoding="utf-8")
    except Exception as e:
        print(f"Kunne ikke skrive til README: {e}")

    # 5. RENDER HTML RAPPORT
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
