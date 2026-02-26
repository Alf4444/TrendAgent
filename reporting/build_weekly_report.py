import json
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# Stier
ROOT = Path(__file__).resolve().parents[1]
HISTORY_FILE = ROOT / "data/history.json"
LATEST_FILE = ROOT / "data/latest.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
TEMPLATE_FILE = ROOT / "templates/weekly.html.j2"
REPORT_FILE = ROOT / "build/weekly.html"

def get_ma(prices, window):
    """Beregner MA, men accepterer færre datapunkter hvis nødvendigt (robust start)"""
    clean_prices = [p for p in prices if p is not None]
    if not clean_prices: return None
    # Hvis vi ikke har 'window' antal dage, så tag hvad vi har
    actual_window = min(len(clean_prices), window)
    relevant = clean_prices[-actual_window:]
    return sum(relevant) / len(relevant)

def build_weekly():
    if not HISTORY_FILE.exists() or not LATEST_FILE.exists():
        print("Fejl: Datafiler mangler.")
        return

    with open(HISTORY_FILE, "r") as f:
        history = json.load(f)
    with open(LATEST_FILE, "r", encoding="utf-8") as f:
        latest_data = json.load(f)
    with open(PORTFOLIO_FILE, "r") as f:
        portfolio = json.load(f)

    # Tidsdata til rapporten
    now = datetime.now()
    date_str = now.strftime("%d-%m-%Y")
    week_num = now.isocalendar()[1]

    # Map ISIN til Navne og YTD fra din latest.json
    names_map = {i['isin']: i.get('name', i['isin']) for i in latest_data}
    ytd_map = {i['isin']: i.get('return_ytd', 0) for i in latest_data}
    
    rows = []
    active_returns = []
    portfolio_alerts = []
    market_opportunities = []

    for isin, price_dict in history.items():
        dates = sorted(price_dict.keys())
        all_prices = [price_dict[d] for d in dates]
        
        if not all_prices: continue

        curr_p = all_prices[-1]
        # Vi prøver MA200, men tager hvad vi har (robusthed)
        ma200 = get_ma(all_prices, 200)
        
        # Uge-ændring (sammenlign med for 7 dage siden eller ældste punkt)
        past_idx = max(0, len(all_prices) - 7)
        past_p = all_prices[past_idx]
        week_chg = ((curr_p - past_p) / past_p * 100) if past_p else 0
        
        # Trend status (UP/DOWN)
        curr_state = "UP" if ma200 and curr_p > ma200 else "DOWN"
        
        # Detect shifts (til alarmer) - HER ER DIN GAMLE LOGIK GENINDSAT
        past_history = all_prices[:past_idx+1]
        past_ma200 = get_ma(past_history, 200) or ma200
        past_state = "UP" if past_ma200 and past_p > past_ma200 else "DOWN"
        
        is_active = portfolio.get(isin, {}).get('active', False)
        fund_name = names_map.get(isin, isin)

        if is_active:
            active_returns.append(week_chg)
            if past_state == "DOWN" and curr_state == "UP":
                portfolio_alerts.append({"name": fund_name, "msg": "🚀 Skiftet til BULL (Over MA)"})
            elif past_state == "UP" and curr_state == "DOWN":
                portfolio_alerts.append({"name": fund_name, "msg": "⚠️ Skiftet til BEAR (Under MA)"})
        elif past_state == "DOWN" and curr_state == "UP":
            market_opportunities.append({"name": fund_name})

        # Beregn momentum og drawdown
        momentum = round(((curr_p - ma200) / ma200 * 100), 1) if ma200 else 0
        ath = max(all_prices)
        drawdown = ((curr_p - ath) / ath * 100) if ath else 0

        rows.append({
            "name": fund_name,
            "is_active": is_active,
            "week_change_pct": week_chg,
            "trend_state": curr_state,
            "momentum": momentum,
            "ytd_return": ytd_map.get(isin, 0),
            "drawdown": drawdown
        })

    if not TEMPLATE_FILE.exists(): 
        print("Fejl: Template mangler")
        return

    # Sortering efter din faste logik
    sorted_rows = sorted(rows, key=lambda x: (not x['is_active'], -x['momentum']))
    
    # Data til grafen
    chart_data = sorted(rows, key=lambda x: x['momentum'], reverse=True)[:10]
    
    current_avg = sum(active_returns)/len(active_returns) if active_returns else 0

    template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
    html_output = template.render(
        report_date=date_str,          # NYT FELT
        week_number=week_num,          # NYT FELT
        avg_portfolio_return=current_avg,
        portfolio_alerts=portfolio_alerts,
        market_opportunities=market_opportunities[:10],
        top_up=sorted(rows, key=lambda x: x['week_change_pct'], reverse=True)[:5],
        top_down=sorted(rows, key=lambda x: x['week_change_pct'])[:5],
        rows=sorted_rows,
        chart_labels=[r['name'][:15] for r in chart_data],
        chart_values=[r['momentum'] for r in chart_data]
    )

    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_output, encoding="utf-8")
    print(f"Weekly Rapport færdig. Analyseret {len(rows)} fonde.")

if __name__ == "__main__":
    build_weekly()
