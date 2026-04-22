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
TEMPLATE_FILE = ROOT / "templates/monthly.html.j2"
REPORT_FILE = ROOT / "build/monthly.html"

BENCHMARK_ISIN = "PFA000002735" # PFA Aktier (Proxy for Profil Høj)

# --- NYE TEKNISKE FUNKTIONER ---
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

# --- DINE ORIGINALE FUNKTIONER ---
def get_ranking_data(latest_list):
    sorted_list = sorted(latest_list, key=lambda x: x.get('return_1m') or -999, reverse=True)
    rank_map = {item['isin']: index + 1 for index, item in enumerate(sorted_list)}
    return rank_map, len(sorted_list)

def get_trend_velocity(f):
    r1w = f.get('return_1w') or 0
    r1m = f.get('return_1m') or 0
    avg_weekly_in_month = r1m / 4
    if r1w > avg_weekly_in_month and r1w > 0:
        return "🚀 Accelererer", "trend-up"
    elif r1w < avg_weekly_in_month:
        return "📉 Bremser", "trend-down"
    return "➡️ Stabil", "trend-side"

def get_momentum_status(f, rank):
    r1m = f.get('return_1m') or 0
    if rank > 10:
        return "🛑 Outperformed", "momentum-flat"
    if r1m < 0 or rank > 7:
        return "⚠️ Slower", "momentum-slow"
    if rank <= 5 and r1m > 0:
        return "🚀 Top Performer", "momentum-fast"
    return "✅ Stabil", "momentum-stable"

def validate_data(latest_map, portfolio):
    warnings = []
    if BENCHMARK_ISIN not in latest_map:
        warnings.append(f"ADVARSEL: Benchmark ISIN {BENCHMARK_ISIN} mangler i data.")
    for isin, p_info in portfolio.items():
        if p_info.get('active', True):
            if isin not in latest_map:
                warnings.append(f"ADVARSEL: Aktiv fond {isin} mangler i PFA-data.")
            if 'buy_price' not in p_info or p_info['buy_price'] <= 0:
                warnings.append(f"ADVARSEL: Købspris mangler for {p_info.get('name', isin)}.")
    return warnings

def build_monthly():
    if not DATA_FILE.exists() or not PORTFOLIO_FILE.exists() or not HISTORY_FILE.exists():
        print("KRITISK FEJL: Data- eller historikfil mangler.")
        return

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

    rank_map, total_market_count = get_ranking_data(latest_list)
    latest_map = {item['isin']: item for item in latest_list}
    validation_warnings = validate_data(latest_map, portfolio)

    now = datetime.now()
    timestamp = now.strftime('%d-%m-%Y %H:%M')
    week_number = now.strftime('%V')

    active_rows = []
    sold_rows = []
    active_returns_total = []

    for isin, p_info in portfolio.items():
        if isin not in latest_map: continue
        
        official = latest_map[isin]
        rank = rank_map.get(isin, 99)
        curr_p = official['nav']
        buy_p = p_info.get('buy_price', 0)
        total_return = ((curr_p - buy_p) / buy_p * 100) if buy_p > 0 else 0
        
        # --- BEREGN RSI & MA FRA HISTORIK ---
        prices = []
        if isin in history:
            # Sorterer datoer for at få korrekt rækkefølge til RSI/MA
            sorted_dates = sorted(history[isin].keys())
            prices = [history[isin][d] for d in sorted_dates]
        
        rsi_val = get_rsi(prices, 14) if prices else None
        ma200_val = get_ma(prices, 200) if prices else None
        
        m_label, m_class = get_momentum_status(official, rank)
        t_label, t_class = get_trend_velocity(official)
        
        fund_data = {
            "isin": isin,
            "name": p_info.get('name', isin),
            "rank": rank,
            "buy_date": p_info.get('buy_date', 'N/A'),
            "buy_price": buy_p,
            "curr_price": curr_p,
            "return_1w": official.get('return_1w') or 0,
            "return_1m": official.get('return_1m') or 0,
            "trend_label": t_label,
            "trend_class": t_class,
            "momentum_label": m_label,
            "momentum_class": m_class,
            "total_return": total_return,
            "rsi": rsi_val,
            "ma200": ma200_val,
            "t_state": "BULL" if ma200_val and curr_p > ma200_val else "BEAR" if ma200_val else "N/A",
            "is_active": p_info.get('active', True)
        }

        if fund_data['is_active']:
            active_rows.append(fund_data)
            active_returns_total.append(total_return)
        else:
            fund_data["sell_date"] = p_info.get('sell_date', 'N/A')
            sold_rows.append(fund_data)

    # Top 5 markedsmuligheder
    unsorted_opps = [i for i in latest_list if i['isin'] not in portfolio or not portfolio[i['isin']].get('active', False)]
    sorted_opps = sorted(unsorted_opps, key=lambda x: x.get('return_1m') or 0, reverse=True)[:5]
    market_opps = []
    for o in sorted_opps:
        t_label, t_class = get_trend_velocity(o)
        market_opps.append({
            "name": o.get('name', o['isin']), 
            "return_1m": o.get('return_1m') or 0,
            "return_ytd": o.get('return_ytd') or 0,   # RETTET: None -> 0 så Jinja2 format() ikke crasher
            "rank": rank_map.get(o['isin']),
            "trend_label": t_label
        })

    sell_signals = [f for f in active_rows if f['momentum_class'] == 'momentum-flat']
    buy_signals = [o for o in market_opps if o['return_1m'] > 4.0]

    benchmark_return = latest_map[BENCHMARK_ISIN].get('return_1m') or 0 if BENCHMARK_ISIN in latest_map else 0
    
    # SIKKERHEDS-RETTELSE MOD DIVISION BY ZERO
    avg_port_return = sum(active_returns_total) / len(active_returns_total) if active_returns_total else 0

    if TEMPLATE_FILE.exists():
        template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
        html_output = template.render(
            timestamp=timestamp,
            week_number=week_number,
            active_funds=sorted(active_rows, key=lambda x: x['rank']),
            sold_funds=sold_rows,
            market_opps=market_opps,
            sell_signals=sell_signals,
            buy_signals=buy_signals,
            benchmark_name="PFA Aktier",
            benchmark_return=benchmark_return,
            avg_portfolio_return=avg_port_return,
            diff_to_benchmark=avg_port_return - benchmark_return,
            warnings=validation_warnings,
            total_market_count=total_market_count
        )
        REPORT_FILE.parent.mkdir(exist_ok=True)
        REPORT_FILE.write_text(html_output, encoding="utf-8")
        print(f"✅ Deep Dive Rapport færdig (Uge {week_number}).")

if __name__ == "__main__":
    build_monthly()
