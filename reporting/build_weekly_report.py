import json
from pathlib import Path
from datetime import datetime, timedelta
from jinja2 import Template

# Stier
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

    # Map ISIN til Navne og YTD data
    names_map = {i['isin']: i.get('name', i['isin']) for i in latest_data}
    
    ytd_map = {}
    for i in latest_data:
        ytd_val = i.get('return_ytd', 0)
        if isinstance(ytd_val, str):
            try:
                ytd_val = float(ytd_val.replace(',', '.'))
            except:
                ytd_val = 0
        ytd_map[i['isin']] = ytd_val
    
    rows = []
    active_returns = []
    portfolio_alerts = []
    market_opportunities = []

    for isin, price_dict in history.items():
        dates = sorted(price_dict.keys())
        all_prices = [price_dict[d] for d in dates]
        
        if len(all_prices) < 200:
            continue

        curr_p = all_prices[-1]
        ma200 = get_ma(all_prices, 200)
        
        past_idx = max(0, len(all_prices) - 7)
        past_p = all_prices[past_idx]
        
        curr_state = "BULL" if curr_p > ma200 else "BEAR"
        
        past_history = all_prices[:past_idx+1]
        past_ma200 = get_ma(past_history, 200) or ma200
        past_state = "BULL" if past_p > past_ma200 else "BEAR"
        
        shift = None
        if past_state == "BEAR" and curr_state == "BULL":
            shift = "UP"
        elif past_state == "BULL" and curr_state == "BEAR":
            shift = "DOWN"

        is_active = portfolio.get(isin, {}).get('active', False)
        fund_name = names_map.get(isin, isin)
        week_chg = ((curr_p - past_p) / past_p * 100)

        if is_active:
            active_returns.append(week_chg)
            if shift == "UP":
                portfolio_alerts.append({"name": fund_name, "msg": "🚀 Skiftet til BULL", "type": "BULL"})
            elif shift == "DOWN":
                portfolio_alerts.append({"name": fund_name, "msg": "⚠️ Skiftet til BEAR", "type": "BEAR"})
        elif shift == "UP":
            market_opportunities.append({"name": fund_name})

        ath = max(all_prices)
        drawdown = ((curr_p - ath) / ath * 100)

        rows.append({
            "name": fund_name,
            "is_active": is_active,
            "change_pct": week_chg,
            "trend_state": curr_state,
            "trend_shift": shift,
            "momentum": round(((curr_p - ma200) / ma200 * 100), 1) if ma200 else 0,
            "ytd": ytd_map.get(isin, 0),
            "drawdown": round(drawdown, 1)
        })

    if not TEMPLATE_FILE.exists():
        print(f"Fejl: Template mangler.")
        return

    sorted_rows = sorted(rows, key=lambda x: (not x['is_active'], -x['momentum']))
    template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
    
    # HER ER RETTELSEN: Vi sender både 'avg_port_ret' OG 'avg_portfolio_return' 
    # for at være helt sikre på at ramme det din template forventer.
    current_avg = sum(active_returns)/len(active_returns) if active_returns else 0

    html_output = template.render(
        timestamp=datetime.now().strftime('%d-%m-%Y'),
        week_num=datetime.now().strftime('%V'),
        rows=sorted_rows,
        portfolio_alerts=portfolio_alerts,
        market_opportunities=market_opportunities[:10],
        avg_port_ret=current_avg,
        avg_portfolio_return=current_avg,
        top_winners=sorted(rows, key=lambda x: x['change_pct'], reverse=True)[:5],
        top_losers=sorted(rows, key=lambda x: x['change_pct'])[:5]
    )

    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_output, encoding="utf-8")
    print(f"Weekly Rapport færdig for uge {datetime.now().strftime('%V')}.")

if __name__ == "__main__":
    build_weekly()
