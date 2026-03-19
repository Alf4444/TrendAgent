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
    """Beregner Moving Average - Robust version."""
    if not isinstance(prices, list):
        return None
    clean_prices = [p for p in prices if (p is not None and isinstance(p, (int, float)))]
    if len(clean_prices) < window:
        return None
    relevant = clean_prices[-window:]
    return sum(relevant) / len(relevant)

def get_rsi(prices, window=14):
    """Beregner RSI - Robust version."""
    if not isinstance(prices, list):
        return None
    clean_prices = [p for p in prices if (p is not None and isinstance(p, (int, float)))]
    if len(clean_prices) <= window:
        return None
    deltas = []
    for i in range(1, len(clean_prices)):
        deltas.append(clean_prices[i] - clean_prices[i-1])
    recent_deltas = deltas[-window:]
    gains = [d if d > 0 else 0 for d in recent_deltas]
    losses = [abs(d) if d < 0 else 0 for d in recent_deltas]
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    if avg_loss == 0: return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1 + rs))

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

    for isin, price_dict in history.items():
        sorted_dates = [d for d in sorted(price_dict.keys()) if is_trading_day(d)]
        if not sorted_dates:
            continue
            
        prices = [price_dict[d] for d in sorted_dates]
        valid_prices = [p for p in prices if (p is not None and isinstance(p, (int, float)))]
        
        if not valid_prices:
            continue
            
        current_nav = valid_prices[-1]
        
        # --- RETTELSE: SIKKER MOMENTUM ---
        # Vi sikrer, at vi aldrig kigger længere tilbage end vi har data til
        idx_w = min(len(valid_prices), 6)
        idx_m = min(len(valid_prices), 21)
        
        p_week = valid_prices[-idx_w]
        p_month = valid_prices[-idx_m]
        
        # Her tjekker vi nu eksplizit for None og 0 før vi regner
        w_chg = 0
        if p_week and p_week != 0:
            w_chg = ((current_nav - p_week) / p_week * 100)
            
        m_chg = 0
        if p_month and p_month != 0:
            m_chg = ((current_nav - p_month) / p_month * 100)
            
        momentum = w_chg - m_chg
        # --------------------------------
        
        ma20 = get_ma(prices, 20)
        ma200 = get_ma(prices, 200)
        rsi = get_rsi(prices, 14)
        
        ma20_dist = 0
        if ma20 is not None and ma20 != 0:
            ma20_dist = ((current_nav - ma20) / ma20 * 100)
        
        p_info = portfolio.get(isin, {})
        is_active = p_info.get('active', False)
        buy_price = p_info.get('buy_price')
        
        t_return = None
        if is_active and isinstance(buy_price, (int, float)) and buy_price > 0:
            t_return = ((current_nav - buy_price) / buy_price * 100)
            active_returns.append(t_return)

        t_state = "WARM-UP"
        if ma200 is not None:
            t_state = "BULL" if current_nav > ma200 else "BEAR"

        rows.append({
            'isin': isin,
            'name': p_info.get('name', isin),
            'nav': current_nav,
            'week_change_pct': w_chg,
            'month_change_pct': m_chg,
            'momentum': momentum,
            'rsi': rsi,
            'is_active': is_active,
            'total_return': t_return,
            't_state': t_state,
            'ma20_dist': ma20_dist
        })

    p_alerts = [r for r in rows if r['is_active'] and r['week_change_pct'] < -3.0]
    m_opps = [r for r in rows if not r['is_active'] and r['momentum'] > 2.0 and r['t_state'] == "BULL"]

    sorted_momentum = sorted(rows, key=lambda x: x['momentum'] if x['momentum'] is not None else -999, reverse=True)[:10]
    chart_labels = [r['name'][:20] for r in sorted_momentum]
    chart_values = [r['momentum'] for r in sorted_momentum]

    if not TEMPLATE_FILE.exists():
        print(f"FEJL: Template mangler")
        return

    avg_p_ret = 0
    if active_returns:
        avg_p_ret = sum(active_returns) / len(active_returns)

    template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
    html_output = template.render(
        report_date=date_str,
        week_number=week_num,
        avg_portfolio_return=avg_p_ret,
        portfolio_alerts=p_alerts,
        market_opportunities=m_opps[:8],
        top_up=sorted(rows, key=lambda x: x['week_change_pct'], reverse=True)[:5],
        top_down=sorted(rows, key=lambda x: x['week_change_pct'])[:5],
        rows=sorted(rows, key=lambda x: (not x['is_active'], -(x['momentum'] or -999))),
        chart_labels=chart_labels,
        chart_values=chart_values
    )

    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_output, encoding="utf-8")
    
    print(f"✅ Weekly Rapport færdig for uge {week_num}.")

if __name__ == "__main__":
    build_weekly()
