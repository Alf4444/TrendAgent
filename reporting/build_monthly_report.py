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
TEMPLATE_FILE = ROOT / "templates/monthly.html.j2"
REPORT_FILE = ROOT / "build/monthly.html"

BENCHMARK_ISIN = "PFA000002735" # PFA Aktier

# ==========================================
# TEKNISKE HJÆLPEFUNKTIONER
# ==========================================

def is_trading_day(date_str):
    """Sikrer at vi kun regner på hverdage."""
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return dt.weekday() < 5
    except:
        return False

def get_ma(prices, window):
    if not prices or len(prices) < window:
        return None
    return sum(prices[-window:]) / window

def get_rsi(prices, window=14):
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

def get_trend_velocity(prices):
    """
    Beregner om prisen accelererer (sidste 5 dage vs sidste 20 dage).
    """
    if len(prices) < 21:
        return "➡️ Stabil", "trend-side"
    
    current = prices[-1]
    week_ago = prices[-6]
    month_ago = prices[-21]
    
    r1w = ((current - week_ago) / week_ago * 100)
    r1m = ((current - month_ago) / month_ago * 100)
    
    # Acceleration: Er den seneste uge bedre end uge-gennemsnittet for måneden?
    avg_weekly_in_month = r1m / 4
    
    if r1w > avg_weekly_in_month and r1w > 0.5:
        return "🚀 Accelererer", "trend-up"
    elif r1w < avg_weekly_in_month and r1w < -0.5:
        return "📉 Bremser", "trend-down"
    
    return "➡️ Stabil", "trend-side"

def get_momentum_status(rank, r1m):
    """Kategoriserer fonden baseret på dens rank i hele PFA universet."""
    if rank <= 5 and r1m > 0:
        return "🚀 Top Performer", "momentum-fast"
    if rank > 15:
        return "🛑 Outperformed", "momentum-flat"
    if r1m < 0 or rank > 10:
        return "⚠️ Slower", "momentum-slow"
    return "✅ Stabil", "momentum-stable"

# ==========================================
# HOVEDFUNKTION
# ==========================================

def build_monthly():
    # 1. BUILD-BUFFER (Retry-logik)
    max_retries = 3
    for attempt in range(max_retries):
        if DATA_FILE.exists():
            file_mod_time = datetime.fromtimestamp(DATA_FILE.stat().st_mtime).date()
            if file_mod_time == datetime.now().date():
                break
        if attempt < max_retries - 1:
            print(f"Måneds-build venter på friske data (Forsøg {attempt+1})...")
            time.sleep(300)

    # 2. INDLÆS DATA
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            latest_list = json.load(f)
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)
    except Exception as e:
        print(f"Fejl ved indlæsning: {e}")
        return

    # Forbered markedsoverblik (Ranking baseret på 1M afkast fra PFA data)
    sorted_market = sorted(latest_list, key=lambda x: x.get('return_1m', -999), reverse=True)
    rank_map = {item['isin']: i + 1 for i, item in enumerate(sorted_market)}
    latest_map = {item['isin']: item for item in latest_list}

    now = datetime.now()
    timestamp = now.strftime('%d-%m-%Y %H:%M')
    
    active_rows = []
    sold_rows = []
    active_returns_total = []

    # 3. ANALYSÉR PORTEFØLJE
    for isin, p_info in portfolio.items():
        if isin not in history: continue
        
        # Rens historik for weekender
        all_dates = sorted(history[isin].keys())
        trading_dates = [d for d in all_dates if is_trading_day(d)]
        prices = [history[isin][d] for d in trading_dates]
        
        if not prices: continue
        
        curr_p = prices[-1]
        buy_p = p_info.get('buy_price', 0)
        rank = rank_map.get(isin, 99)
        
        # Beregn månedligt afkast fra historik (20 handelsdage)
        prev_month_p = prices[-21] if len(prices) >= 21 else prices[0]
        r1m_calc = ((curr_p - prev_month_p) / prev_month_p * 100)
        
        # Tekniske metrics
        t_label, t_class = get_trend_velocity(prices)
        m_label, m_class = get_momentum_status(rank, r1m_calc)
        ma200 = get_ma(prices, 200)
        rsi = get_rsi(prices, 14)
        
        fund_data = {
            "isin": isin,
            "name": p_info.get('name', isin),
            "sector": p_info.get('sector', 'Ukendt'),
            "rank": rank,
            "buy_date": p_info.get('buy_date', 'N/A'),
            "curr_price": curr_p,
            "return_1m": r1m_calc,
            "rsi": rsi,
            "trend_label": t_label,
            "trend_class": t_class,
            "momentum_label": m_label,
            "momentum_class": m_class,
            "total_return": ((curr_p - buy_p) / buy_p * 100) if buy_p > 0 else 0,
            "is_active": p_info.get('active', True),
            "t_state": "BULL" if ma200 and curr_p > ma200 else "BEAR" if ma200 else "WARM-UP"
        }

        if fund_data['is_active']:
            active_rows.append(fund_data)
            active_returns_total.append(fund_data['total_return'])
        else:
            fund_data["sell_date"] = p_info.get('sell_date', 'N/A')
            sold_rows.append(fund_data)

    # 4. MARKEDSMULIGHEDER (Top 5 som ikke ejes)
    market_opps = []
    potential = [i for i in latest_list if i['isin'] not in portfolio or not portfolio[i['isin']].get('active', False)]
    sorted_opps = sorted(potential, key=lambda x: x.get('return_1m', 0), reverse=True)[:5]
    
    for o in sorted_opps:
        # Vi prøver at hente trend fra historik hvis muligt
        o_prices = [history[o['isin']][d] for d in sorted(history.get(o['isin'], {}).keys()) if is_trading_day(d)]
        t_label, _ = get_trend_velocity(o_prices) if o_prices else ("N/A", "")
        
        market_opps.append({
            "name": o.get('name', o['isin']), 
            "return_1m": o.get('return_1m', 0), 
            "rank": rank_map.get(o['isin']),
            "trend_label": t_label
        })

    # 5. BENCHMARK SAMMENLIGNING
    benchmark_return = latest_map[BENCHMARK_ISIN].get('return_1m', 0) if BENCHMARK_ISIN in latest_map else 0
    avg_port_return = statistics.mean(active_returns_total) if active_returns_total else 0

    # 6. RENDER HTML
    if TEMPLATE_FILE.exists():
        template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
        html_output = template.render(
            timestamp=timestamp,
            active_funds=sorted(active_rows, key=lambda x: x['rank']),
            sold_funds=sold_rows,
            market_opps=market_opps,
            benchmark_name="PFA Aktier",
            benchmark_return=benchmark_return,
            avg_portfolio_return=avg_port_return,
            diff_to_benchmark=avg_port_return - benchmark_return,
            total_market_count=len(latest_list)
        )
        REPORT_FILE.parent.mkdir(exist_ok=True)
        REPORT_FILE.write_text(html_output, encoding="utf-8")
        print(f"✅ Monthly Deep Dive færdig. Alpha: {avg_port_return - benchmark_return:+.2f}%")

if __name__ == "__main__":
    build_monthly()
