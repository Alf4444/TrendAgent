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
    # Tjek 1: Er listen overhovedet en liste?
    if prices is None:
        return None
    
    # Tjek 2: Rens for None-værdier
    clean_prices = [p for p in prices if p is not None]
    
    # Tjek 3: Er der nok data til det ønskede vindue?
    if not clean_prices or len(clean_prices) < window:
        return None
        
    relevant = clean_prices[-window:]
    return sum(relevant) / len(relevant)

def get_rsi(prices, window=14):
    """Beregner RSI - Robust version mod None og korte serier."""
    # Tjek 1: Er listen gyldig?
    if prices is None:
        return None
        
    # Tjek 2: Rens for None-værdier
    clean_prices = [p for p in prices if p is not None]
    
    # Tjek 3: RSI kræver vindue + 1 priser for at beregne deltas
    if len(clean_prices) <= window:
        return None
        
    deltas = []
    for i in range(1, len(clean_prices)):
        deltas.append(clean_prices[i] - clean_prices[i-1])
        
    # Tag kun de seneste deltas svarende til vinduet
    recent_deltas = deltas[-window:]
    
    gains = [d if d > 0 else 0 for d in recent_deltas]
    losses = [abs(d) if d < 0 else 0 for d in recent_deltas]
    
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    
    if avg_loss == 0: 
        return 100
        
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
        # 1. Hent og sorter hverdage
        sorted_dates = [d for d in sorted(price_dict.keys()) if is_trading_day(d)]
        if not sorted_dates:
            continue
            
        # 2. Skab prisliste (kan indeholde None fra JSON)
        prices = [price_dict[d] for d in sorted_dates]
        
        # 3. Rens til rent numerisk liste til direkte afkast-beregning
        valid_prices = [p for p in prices if p is not None]
        if not valid_prices:
            continue
            
        current_nav = valid_prices[-1]
        
        # 4. Beregn momentum (Uge vs Måned)
        # Vi sikrer os at vi ikke kigger længere tilbage end vi har data til
        idx_week = min(len(valid_prices), 6)
        idx_month = min(len(valid_prices), 21)
        
        prev_week_nav = valid_prices[-idx_week]
        prev_month_nav = valid_prices[-idx_month]
        
        week_chg = ((current_nav - prev_week_nav) / prev_week_nav * 100) if prev_week_nav else 0
        month_chg = ((current_nav - prev_month_nav) / prev_month_nav * 100) if prev_month_nav else 0
        momentum = week_chg - month_chg
        
        # 5. Tekniske indikatorer via de robuste funktioner
        ma20 = get_ma(prices, 20)
        ma200 = get_ma(prices, 200)
        rsi = get_rsi(prices, 14)
        
        # 6. Portefølje-status
        p_info = portfolio.get(isin, {})
        is_active = p_info.get('active', False)
        buy_price = p_info.get('buy_price')
        
        total_return = None
        if is_active and buy_price and buy_price > 0:
            total_return = ((current_nav - buy_price) / buy_price * 100)
            active_returns.append(total_return)

        # 7. Trend definition
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

    # 8. Sortering og filtrering til rapporten
    portfolio_alerts = [r for r in rows if r['is_active'] and r['week_change_pct'] < -3.0]
    market_opportunities = [r for r in rows if not r['is_active'] and r['momentum'] > 2.0 and r['t_state'] == "BULL"]

    # 9. Graf-data
    sorted_momentum = sorted(rows, key=lambda x: x['momentum'], reverse=True)[:10]
    chart_labels = [r['name'][:20] for r in sorted_momentum]
    chart_values = [r['momentum'] for r in sorted_momentum]

    if not TEMPLATE_FILE.exists():
        print(f"FEJL: Template mangler på {TEMPLATE_FILE}")
        return

    # 10. Sikker beregning af portefølje-gennemsnit
    if active_returns:
        avg_port_return = statistics.mean(active_returns)
    else:
        avg_port_return = 0

    # 11. Render og gem
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

    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_output, encoding="utf-8")
    
    print(f"✅ Weekly Rapport færdig for uge {week_num}.")

if __name__ == "__main__":
    build_weekly()
