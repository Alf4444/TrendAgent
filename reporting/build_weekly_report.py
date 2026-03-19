import json
import time
import statistics
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# ==========================================
# KONFIGURATION & STIER
# ==========================================
ROOT = Path(__file__).resolve().parents[1]
HISTORY_FILE = ROOT / "data/history.json"
LATEST_FILE = ROOT / "data/latest.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
TEMPLATE_FILE = ROOT / "templates/weekly.html.j2"
REPORT_FILE = ROOT / "build/weekly.html"

# ==========================================
# TEKNISKE HJÆLPEFUNKTIONER
# ==========================================

def get_ma(prices, window):
    """Beregner Moving Average kun hvis der er data nok (ingen warm-up)."""
    if not prices or len(prices) < window:
        return None
    relevant = prices[-window:]
    return sum(relevant) / len(relevant)

def get_rsi(prices, window=14):
    """Beregner Relative Strength Index (RSI) baseret på hverdage."""
    if len(prices) <= window:
        return None
    deltas = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas[-window:]]
    losses = [abs(d) if d < 0 else 0 for d in deltas[-window:]]
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    if avg_loss == 0: return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def is_trading_day(date_str):
    """Filterer weekender fra."""
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return dt.weekday() < 5
    except:
        return False

# ==========================================
# HOVEDFUNKTION
# ==========================================

def build_weekly():
    # 1. BUILD-BUFFER (Retry-logik)
    max_retries = 3
    retry_delay = 300
    
    for attempt in range(max_retries):
        if LATEST_FILE.exists():
            file_mod_time = datetime.fromtimestamp(LATEST_FILE.stat().st_mtime).date()
            if file_mod_time == datetime.now().date():
                break
        if attempt < max_retries - 1:
            print(f"Uge-build venter på friske data (Forsøg {attempt+1})...")
            time.sleep(retry_delay)

    # 2. DATAINDLÆSNING
    if not HISTORY_FILE.exists() or not PORTFOLIO_FILE.exists():
        print("FEJL: Kritiske filer mangler.")
        return

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)
    except Exception as e:
        print(f"Fejl ved indlæsning: {e}")
        return

    rows = []
    active_returns = []
    date_str = datetime.now().strftime("%d-%m-%Y")
    week_num = datetime.now().isocalendar()[1]

    # 3. ANALYSE AF HVER FOND
    for isin, price_dict in history.items():
        # Filtrér til kun hverdage
        sorted_dates = [d for d in sorted(price_dict.keys()) if is_trading_day(d)]
        if not sorted_dates:
            continue
            
        prices = [price_dict[d] for d in sorted_dates]
        current_nav = prices[-1]
        
        # --- Ugentlig Momentum ---
        # Vi kigger præcis 5 handelsdage tilbage for en "uge"
        prev_week_nav = prices[-6] if len(prices) >= 6 else prices[0]
        # Vi kigger 20 handelsdage tilbage for en "måned"
        prev_month_nav = prices[-21] if len(prices) >= 21 else prices[0]
        
        week_chg = ((current_nav - prev_week_nav) / prev_week_nav * 100)
        month_chg = ((current_nav - prev_month_nav) / prev_month_nav * 100)
        
        # Momentum score (relativ styrke: uge vs måned)
        momentum = week_chg - month_chg
        
        # Tekniske indikatorer
        ma20 = get_ma(prices, 20)
        ma200 = get_ma(prices, 200)
        rsi = get_rsi(prices, 14)
        
        # Portefølje info
        p_info = portfolio.get(isin, {})
        is_active = p_info.get('active', False)
        buy_price = p_info.get('buy_price')
        sector = p_info.get('sector', 'Ukendt')
        
        total_return = None
        if is_active and buy_price:
            total_return = ((current_nav - buy_price) / buy_price * 100)
            active_returns.append(total_return)

        # Trend status
        t_state = "WARM-UP"
        if ma200:
            t_state = "BULL" if current_nav > ma200 else "BEAR"

        rows.append({
            'isin': isin,
            'name': p_info.get('name', isin),
            'sector': sector,
            'nav': current_nav,
            'week_change_pct': week_chg,
            'month_change_pct': month_chg,
            'momentum': momentum,
            'rsi': rsi,
            'is_active': is_active,
            'total_return': total_return,
            't_state': t_state,
            'ma20_dist': ((current_nav - ma20) / ma20 * 100) if ma20 else 0
        })

    # 4. ALERTS & OPSUMMERING
    portfolio_alerts = [r for r in rows if r['is_active'] and r['week_change_pct'] < -3.0]
    market_opportunities = [r for r in rows if not r['is_active'] and r['momentum'] > 2.0 and r['t_state'] == "BULL"]

    # 5. SORTERING & GRAF-DATA
    # Top 10 momentum til grafen
    sorted_momentum = sorted(rows, key=lambda x: x['momentum'], reverse=True)[:10]
    chart_labels = [r['name'][:20] for r in sorted_momentum]
    chart_values = [r['momentum'] for r in sorted_momentum]

    # 6. RENDER TEMPLATE
    if not TEMPLATE_FILE.exists():
        print(f"FEJL: Template mangler på {TEMPLATE_FILE}")
        return

    template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
    html_output = template.render(
        report_date=date_str,
        week_number=week_num,
        avg_portfolio_return=statistics.mean(active_returns) if active_returns else 0,
        portfolio_alerts=portfolio_alerts,
        market_opportunities=market_opportunities,
        top_up=sorted(rows, key=lambda x: x['week_change_pct'], reverse=True)[:5],
        top_down=sorted(rows, key=lambda x: x['week_change_pct'])[:5],
        rows=sorted(rows, key=lambda x: (not x['is_active'], -x['momentum'])),
        chart_labels=chart_labels,
        chart_values=chart_values
    )

    # 7. GEM RAPPORT
    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_output, encoding="utf-8")
    
    print(f"Weekly Rapport færdig for uge {week_num}.")

if __name__ == "__main__":
    build_weekly()
