import json
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
    """Beregner Moving Average."""
    if not prices or len(prices) < window:
        return None
    relevant = prices[-window:]
    return sum(relevant) / len(relevant)

def get_rsi(prices, window=14):
    """Beregner Relative Strength Index (RSI)."""
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
    # 1. DATAINDLÆSNING
    if not HISTORY_FILE.exists() or not PORTFOLIO_FILE.exists():
        print("FEJL: Kritiske filer mangler.")
        return

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)
        
        # Latest er valgfri for ekstra robusthed
        latest_map = {}
        if LATEST_FILE.exists():
            with open(LATEST_FILE, "r", encoding="utf-8") as f:
                l_data = json.load(f)
                latest_map = {i['isin']: i for i in l_data}
    except Exception as e:
        print(f"Fejl ved indlæsning: {e}")
        return

    rows = []
    active_returns = []
    date_str = datetime.now().strftime("%d-%m-%Y")
    week_num = datetime.now().isocalendar()[1]

    # 2. ANALYSE AF HVER FOND
    for isin, price_dict in history.items():
        # Sorter hverdage
        sorted_dates = [d for d in sorted(price_dict.keys()) if is_trading_day(d)]
        if not sorted_dates:
            continue
            
        prices = [price_dict[d] for d in sorted_dates]
        current_nav = prices[-1]
        
        # Beregn ændringer
        prev_week_nav = prices[-6] if len(prices) >= 6 else prices[0]
        prev_month_nav = prices[-21] if len(prices) >= 21 else prices[0]
        
        week_chg = ((current_nav - prev_week_nav) / prev_week_nav * 100)
        month_chg = ((current_nav - prev_month_nav) / prev_month_nav * 100)
        momentum = week_chg - month_chg
        
        # Tekniske indikatorer
        ma20 = get_ma(prices, 20)
        ma200 = get_ma(prices, 200)
        rsi = get_rsi(prices, 14)
        
        # Portefølje data
        p_info = portfolio.get(isin, {})
        is_active = p_info.get('active', False)
        buy_price = p_info.get('buy_price')
        
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

    # 3. ALERTS & OPSUMMERING
    portfolio_alerts = [r for r in rows if r['is_active'] and r['week_change_pct'] < -3.0]
    market_opportunities = [r for r in rows if not r['is_active'] and r['momentum'] > 2.0 and r['t_state'] == "BULL"]

    # 4. GRAF-DATA
    sorted_momentum = sorted(rows, key=lambda x: x['momentum'], reverse=True)[:10]
    chart_labels = [r['name'][:20] for r in sorted_momentum]
    chart_values = [r['momentum'] for r in sorted_momentum]

    # 5. RENDER TEMPLATE
    if not TEMPLATE_FILE.exists():
        print(f"FEJL: Template mangler")
        return

    # SIKKERHEDSNET: Bruger statistics.mean hvis listen ikke er tom
    avg_port_return = statistics.mean(active_returns) if active_returns else 0

    template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
    html_output = template.render(
        report_date=date_str,
        week_number=week_num,
        avg_portfolio_return=avg_port_return,
        portfolio_alerts=portfolio_alerts,
        market_opportunities=market_opportunities,
        top_up=sorted(rows, key=lambda x: x['week_change_pct'], reverse=True)[:5],
        top_down=sorted(rows, key=lambda x: x['week_change_pct'])[:5],
        rows=sorted(rows, key=lambda x: (not x['is_active'], -x['momentum'])),
        chart_labels=chart_labels,
        chart_values=chart_values
    )

    # 6. GEM FIL
    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_output, encoding="utf-8")
    
    print(f"✅ Weekly Rapport færdig for uge {week_num}.")

if __name__ == "__main__":
    build_weekly()
