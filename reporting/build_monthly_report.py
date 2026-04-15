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

# --- TEKNISKE FUNKTIONER (Original logik bevaret) ---
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

def get_drawdown(prices):
    if not prices: return 0
    ath = max(prices)
    current = prices[-1]
    return ((current - ath) / ath) * 100

def build_monthly():
    # 1. INITIALISERING (Fixer UndefinedError i Jinja2)
    timestamp = datetime.now().strftime("%d-%m-%Y %H:%M")
    week_number = datetime.now().isocalendar()[1]
    active_rows = []
    sold_rows = []
    market_opps = []
    active_returns_total = []
    validation_warnings = []
    chart_labels = []   # SIKRING: Altid defineret
    chart_values = []   # SIKRING: Altid defineret

    # 2. Indlæs filer
    try:
        latest_data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        history_data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        portfolio = json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"Kritisk fejl ved indlæsning: {e}")
        return

    my_isins = [p['isin'] for p in portfolio]
    latest_map = {f['isin']: f for f in latest_data}
    
    # 3. Beregn rankings og trends (Skiftet til MA50 pga. historik)
    temp_ranks = []
    for isin, prices_dict in history_data.items():
        if isin not in latest_map: continue
        
        prices = list(prices_dict.values())
        ma_val = get_ma(prices, 50) # Ændret fra 200 til 50
        nav = latest_map[isin]['nav']
        
        if ma_val:
            mom = ((nav - ma_val) / ma_val) * 100
            temp_ranks.append({'isin': isin, 'mom': mom})

    temp_ranks.sort(key=lambda x: x['mom'], reverse=True)
    rank_map = {item['isin']: i+1 for i, item in enumerate(temp_ranks)}

    # 4. Processér alle fonde
    for isin, prices_dict in history_data.items():
        if isin not in latest_map: continue
        
        fund = latest_map[isin]
        prices = list(prices_dict.values())
        ma_val = get_ma(prices, 50) # Ændret fra 200 til 50
        rsi = get_rsi(prices)
        dd = get_drawdown(prices)
        
        momentum = 0
        t_label = "Afventer data"
        m_class = "momentum-flat"

        if ma_val:
            momentum = ((fund['nav'] - ma_val) / ma_val) * 100
            if momentum > 0:
                t_label = "Positiv"
                m_class = "momentum-up"
            else:
                t_label = "Negativ"
                m_class = "momentum-down"

        row = {
            "isin": isin,
            "name": fund['name'],
            "nav": fund['nav'],
            "rsi": round(rsi, 1) if rsi else 0,
            "dd": round(dd, 2),
            "momentum": round(momentum, 2),
            "momentum_class": m_class,
            "return_1m": fund.get('return_1m', 0) or 0,
            "return_ytd": fund.get('return_ytd', 0) or 0,
            "rank": rank_map.get(isin, 999),
            "trend_label": t_label
        }

        if isin in my_isins:
            active_rows.append(row)
            active_returns_total.append(row['return_1m'])
        else:
            market_opps.append(row)

    # 5. Forbered graf (Top 10 momentum)
    display_source = active_rows if active_rows else market_opps
    if display_source:
        display_trends = sorted(display_source, key=lambda x: x['momentum'], reverse=True)[:10]
        chart_labels = [t['name'][:20] for t in display_trends]
        chart_values = [t['momentum'] for t in display_trends]

    # 6. Salgs- og Købssignaler
    sell_signals = [f for f in active_rows if f['momentum'] < 0]
    buy_signals = [o for o in market_opps if o['momentum'] > 5.0 and o['rsi'] < 70]

    # 7. Benchmark og stats
    benchmark_return = latest_map[BENCHMARK_ISIN].get('return_1m', 0) if BENCHMARK_ISIN in latest_map else 0
    # SIKRING: Undgå division med nul
    avg_port_return = sum(active_returns_total) / len(active_returns_total) if active_returns_total else 0

    # 8. Render og gem rapport
    if TEMPLATE_FILE.exists():
        template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
        html_output = template.render(
            timestamp=timestamp,
            week_number=week_number,
            active_funds=sorted(active_rows, key=lambda x: x['rank']),
            sold_funds=sold_rows,
            market_opps=sorted(market_opps, key=lambda x: x['momentum'], reverse=True)[:15],
            sell_signals=sell_signals,
            buy_signals=buy_signals,
            chart_labels=chart_labels,
            chart_values=chart_values,
            benchmark_name="PFA Aktier",
            benchmark_return=benchmark_return,
            avg_portfolio_return=avg_port_return,
            diff_to_benchmark=avg_port_return - benchmark_return,
            warnings=validation_warnings,
            total_market_count=len(latest_data)
        )
        
        REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.write_text(html_output, encoding="utf-8")
        print(f"Månedsrapport færdig: {REPORT_FILE}")
    else:
        print(f"Fejl: Kunne ikke finde template: {TEMPLATE_FILE}")

if __name__ == "__main__":
    build_monthly()
