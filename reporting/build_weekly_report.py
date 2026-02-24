import json
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# Stier baseret på din faste struktur
ROOT = Path(__file__).resolve().parents[1]
HISTORY_FILE = ROOT / "data/history.json"
LATEST_FILE = ROOT / "data/latest.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
TEMPLATE_FILE = ROOT / "templates/weekly.html.j2"
REPORT_FILE = ROOT / "build/weekly.html"

def get_ma(prices, window):
    if not prices or len(prices) < window:
        return None
    relevant = prices[-window:]
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

    # Map ISIN til Navne og YTD data fra latest.json
    names_map = {i['isin']: i.get('name', i['isin']) for i in latest_data}
    
    # YTD returnering (sikrer float konvertering fra streng hvis nødvendigt)
    ytd_map = {}
    for i in latest_data:
        val = i.get('return_ytd', 0)
        if isinstance(val, str):
            try: val = float(val.replace(',', '.'))
            except: val = 0
        ytd_map[i['isin']] = val
    
    rows = []
    active_returns = []
    portfolio_alerts = []
    market_opportunities = []

    for isin, price_dict in history.items():
        # Sorter datoer og find priser
        dates = sorted(price_dict.keys())
        all_prices = [price_dict[d] for d in dates]
        
        if len(all_prices) < 200:
            continue

        curr_p = all_prices[-1]
        ma200 = get_ma(all_prices, 200)
        
        # 7-dages analyse
        past_idx = max(0, len(all_prices) - 7)
        past_p = all_prices[past_idx]
        
        # Trend status (Matcher template: 'UP' for BULL, 'DOWN' for BEAR)
        curr_state = "UP" if curr_p > (ma200 or 0) else "DOWN"
        
        # Trend shift detektion
        past_history = all_prices[:past_idx+1]
        past_ma200 = get_ma(past_history, 200) or ma200
        past_state = "UP" if past_p > past_ma200 else "DOWN"
        
        shift = None
        if past_state == "DOWN" and curr_state == "UP": shift = "UP"
        elif past_state == "UP" and curr_state == "DOWN": shift = "DOWN"

        is_active = portfolio.get(isin, {}).get('active', False)
        fund_name = names_map.get(isin, isin)
        week_chg = ((curr_p - past_p) / past_p * 100)

        if is_active:
            active_returns.append(week_chg)
            if shift == "UP":
                portfolio_alerts.append({"name": fund_name, "msg": "🚀 Skiftet til BULL"})
            elif shift == "DOWN":
                portfolio_alerts.append({"name": fund_name, "msg": "⚠️ Skiftet til BEAR"})
        elif shift == "UP":
            market_opportunities.append({"name": fund_name})

        # Beregn Drawdown (fald fra top i historikken)
        ath = max(all_prices)
        dd = ((curr_p - ath) / ath * 100)

        # Hver række SKAL indeholde disse præcise navne til templaten
        rows.append({
            "name": fund_name,
            "is_active": is_active,
            "week_change_pct": week_chg,
            "trend_state": curr_state,
            "momentum": round(((curr_p - ma200) / ma200 * 100), 1) if ma200 else 0,
            "ytd_return": ytd_map.get(isin, 0),
            "drawdown": dd
        })

    if not TEMPLATE_FILE.exists():
        print("Fejl: Template mangler.")
        return

    # Sortering: Aktive først, derefter momentum
    sorted_rows = sorted(rows, key=lambda x: (not x['is_active'], -x['momentum']))
    
    # Data til grafen (Top 10 momentum fonde)
    chart_data = sorted(rows, key=lambda x: x['momentum'], reverse=True)[:10]
    
    current_avg = sum(active_returns)/len(active_returns) if active_returns else 0

    template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
    
    # Render med de PRÆCISE variable din HTML efterspørger
    html_output = template.render(
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
    print(f"Weekly Rapport færdig: Analyseret {len(rows)} fonde.")

if __name__ == "__main__":
    build_weekly()
