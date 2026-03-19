import json
import time
import statistics
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

# ==========================================
# TEKNISKE HJÆLPEFUNKTIONER
# ==========================================

def get_ma(prices, window):
    """Beregner glidende gennemsnit (MA) kun hvis der er data nok."""
    if not prices or len(prices) < window:
        return None
    relevant_prices = prices[-window:]
    return sum(relevant_prices) / len(relevant_prices)

def get_rsi(prices, window=14):
    """Beregner Relative Strength Index (RSI)."""
    if len(prices) <= window:
        return None
    
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas[-window:]]
    losses = [abs(d) if d < 0 else 0 for d in deltas[-window:]]
    
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def get_volatility(prices, window=20):
    """Beregner den historiske volatilitet (standardafvigelse af %-ændringer)."""
    if len(prices) < window:
        return None
    
    relevant = prices[-window:]
    # Beregn daglige procentvise ændringer
    pct_changes = [((relevant[i] - relevant[i-1]) / relevant[i-1] * 100) for i in range(1, len(relevant))]
    
    if len(pct_changes) < 2:
        return 0
    return statistics.stdev(pct_changes)

def is_trading_day(date_str):
    """Tjekker om en dato-streng (YYYY-MM-DD) er en hverdag."""
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return dt.weekday() < 5 # 0-4 er mandag-fredag
    except:
        return False

# ==========================================
# HOVEDFUNKTION
# ==========================================

def build_report():
    # 1. RETRY-LOGIK (Build-buffer)
    # Tjekker om data er opdateret for i dag før vi starter
    max_retries = 3
    retry_delay = 300 # 5 minutter
    
    latest_data = []
    for attempt in range(max_retries):
        if not DATA_FILE.exists():
            print(f"FEJL: {DATA_FILE} mangler.")
            return

        with open(DATA_FILE, "r", encoding="utf-8") as f:
            latest_data = json.load(f)
        
        # Tjek datoen på det første element i latest_data (hvis formatet tillader det)
        # Hvis PFA data ikke er kommet endnu, venter vi.
        file_mod_time = datetime.fromtimestamp(DATA_FILE.stat().st_mtime).date()
        if file_mod_time == datetime.now().date():
            print(f"Data er frisk (fra i dag {file_mod_time}). Starter build...")
            break
        else:
            if attempt < max_retries - 1:
                print(f"Forsøg {attempt+1}: Data i {DATA_FILE.name} er fra i går. Venter {retry_delay/60} minutter...")
                time.sleep(retry_delay)
            else:
                print("Advarsel: Kører build på gårsdagens data, da PFA ikke har opdateret endnu.")

    # 2. INDLÆS ØVRIGE FILER
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)
    except Exception as e:
        print(f"Fejl ved indlæsning af filer: {e}")
        return

    timestamp = datetime.now().strftime('%d-%m-%Y %H:%M')
    processed_list = []

    # 3. BEHANDL HVER FOND
    for item in latest_data:
        isin = item.get('isin')
        nav = item.get('nav')
        if nav is None or isin is None:
            continue
        
        # Hent historik og filtrér WEEKENDER fra
        price_dict = history.get(isin, {})
        # Kun hverdage tæller i den tekniske analyse
        sorted_dates = [d for d in sorted(price_dict.keys()) if is_trading_day(d)]
        price_history = [price_dict[d] for d in sorted_dates]
        
        # Sikr at dagens NAV er med, hvis den ikke allerede er i historikken
        if not price_history or price_history[-1] != nav:
            price_history.append(nav)

        # --- TEKNISKE BEREGNINGER ---
        # Nu med validering (returnerer None hvis < vindue)
        ma20 = get_ma(price_history, 20)
        ma50 = get_ma(price_history, 50)
        ma200 = get_ma(price_history, 200)
        rsi = get_rsi(price_history, 14)
        volatility = get_volatility(price_history, 20)
        
        # Afstand til MA200
        dist_ma200 = ((nav - ma200) / ma200 * 100) if ma200 else 0
        
        # CROSS logik (Kun hvis begge MA findes)
        cross_20_50 = "–"
        if ma20 and ma50:
            # Vi kigger på de forrige værdier for at finde krydset
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

        # Drawdown
        ath = max(price_history) if price_history else nav
        drawdown = ((nav - ath) / ath * 100) if ath > 0 else 0
        
        # Portefølje data
        p_info = portfolio.get(isin, {})
        is_active = p_info.get('active', False)
        buy_p = p_info.get('buy_price')
        sector = p_info.get('sector', 'Ukendt')
        total_return = ((nav - buy_p) / buy_p * 100) if is_active and buy_p else None
        
        # Stop-loss flag
        stop_alert = False
        if drawdown <= -10.0 or (is_active and total_return and total_return <= -8.0):
            stop_alert = True

        processed_list.append({
            'isin': isin, 
            'name': item.get('name'),
            'sector': sector,
            'day_chg': day_chg, 
            'dist_ma200': dist_ma200,
            'rsi': rsi,
            'volatility': volatility,
            'signal': signal, 
            'has_signal': has_signal,
            'is_active': is_active, 
            'drawdown': drawdown,
            'cross_20_50': cross_20_50, 
            'total_return': total_return,
            'stop_alert': stop_alert,
            't_state': "BULL" if ma200 and nav > ma200 else "BEAR" if ma200 else "WARM-UP"
        })

    # 4. SORTERING
    processed_list.sort(key=lambda x: (
        not x['is_active'],    
        x['signal'] == "–",     
        x['name']               
    ))

    # Outliers
    outliers = sorted(processed_list, key=lambda x: x['day_chg'] or 0, reverse=True)
    top_3 = outliers[:3]
    bottom_3 = outliers[-3:][::-1]

    # 5. OPDATER README.MD
    readme_content = f"# 📈 TrendAgent Fokus\n**Opdateret:** {timestamp} (Handelsdage valideret)\n\n"
    readme_content += "| | Fond | Signal | RSI | Egen % | Trend | Afstand | Cross |\n| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
    for d in processed_list:
        if d['is_active'] or d['has_signal']:
            ret = f"{d['total_return']:+.1f}%" if d['total_return'] is not None else "–"
            rsi_val = f"{d['rsi']:.0f}" if d['rsi'] is not None else "–"
            alert_prefix = "⚠️ " if d.get('stop_alert') else ""
            
            readme_content += (f"| {'⭐' if d['is_active'] else '🔍'} | "
                             f"{alert_prefix}{d['name'][:25]} | "
                             f"{d['signal']} | {rsi_val} | {ret} | {d['t_state']} | "
                             f"{d['dist_ma200']:+.1f}% | {d['cross_20_50']} |\n")
    
    try:
        README_FILE.write_text(readme_content, encoding="utf-8")
    except Exception as e:
        print(f"Kunne ikke skrive til README: {e}")

    # 6. RENDER HTML RAPPORT
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
