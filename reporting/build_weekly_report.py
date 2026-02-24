import json
from pathlib import Path
from datetime import datetime, timedelta
from jinja2 import Template

ROOT = Path(__file__).resolve().parents[1]
HISTORY_FILE = ROOT / "data/history.json"
LATEST_FILE = ROOT / "data/latest.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
TEMPLATE_FILE = ROOT / "templates/weekly.html.j2"
REPORT_FILE = ROOT / "build/weekly.html"

def calculate_ma(prices, window=200):
    if not prices or len(prices) < 5: return 0
    relevant = prices[-window:]
    return sum(relevant) / len(relevant)

def build_weekly():
    if not HISTORY_FILE.exists() or not LATEST_FILE.exists(): return

    with open(HISTORY_FILE, "r") as f: history = json.load(f)
    with open(LATEST_FILE, "r", encoding="utf-8") as f: latest_list = json.load(f)
    
    portfolio = {}
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE, "r") as f: portfolio = json.load(f)

    names_map = {i['isin']: i.get('name', i['isin']) for i in latest_list}
    latest_map = {i['isin']: i for i in latest_list}
    rows = []
    portfolio_alerts = []
    market_opportunities = []
    active_returns = []
    
    for isin, prices_dict in history.items():
        dates = sorted(prices_dict.keys())
        if len(dates) < 5: continue
        
        curr_nav = prices_dict[dates[-1]]
        all_prices = [prices_dict[d] for d in dates]
        curr_ma200 = calculate_ma(all_prices, 200)
        curr_state = "UP" if curr_nav > curr_ma200 else "DOWN"
        
        target_date = datetime.strptime(dates[-1], "%Y-%m-%d") - timedelta(days=7)
        past_date = min(dates, key=lambda d: abs((datetime.strptime(d, "%Y-%m-%d") - target_date).days))
        past_nav = prices_dict[past_date]
        past_state = "UP" if past_nav > calculate_ma(all_prices[:dates.index(past_date)+1], 200) else "DOWN"
        
        is_active = portfolio.get(isin, {}).get('active', False)
        fund_name = names_map.get(isin, isin)

        if is_active:
            if past_state == "DOWN" and curr_state == "UP":
                portfolio_alerts.append({"name": fund_name, "msg": "🚀 Skiftet til BULL", "type": "BULL"})
            elif past_state == "UP" and curr_state == "DOWN":
                portfolio_alerts.append({"name": fund_name, "msg": "⚠️ Skiftet til BEAR", "type": "BEAR"})
        elif past_state == "DOWN" and curr_state == "UP":
            market_opportunities.append({"name": fund_name})

        momentum = ((curr_nav - curr_ma200) / curr_ma200 * 100) if curr_ma200 > 0 else 0
        week_change = ((curr_nav - past_nav) / past_nav * 100) if past_nav else 0
        if is_active: active_returns.append(week_change)

        rows.append({
            "name": fund_name, "is_active": is_active, "week_change_pct": week_change,
            "trend_state": curr_state, "momentum": round(momentum, 2),
            "ytd_return": float(str(latest_map.get(isin, {}).get('return_ytd', 0)).replace(',', '.')),
            "drawdown": ((curr_nav - max(all_prices)) / max(all_prices) * 100) if max(all_prices) > 0 else 0
        })

    top_up = sorted(rows, key=lambda x: x['week_change_pct'], reverse=True)[:5]
    top_down = sorted(rows, key=lambda x: x['week_change_pct'])[:5]
    avg_return = sum(active_returns) / len(active_returns) if active_returns else 0
    
    table_rows = sorted(rows, key=lambda x: (not x['is_active'], -x['momentum']))
    chart_rows = [r for r in table_rows if r['is_active']][:10]

    template_html = TEMPLATE_FILE.read_text(encoding="utf-8")
    output = Template(template_html).render(
        week_label=datetime.now().strftime("%V"),
        week_end_date=datetime.now().strftime("%d-%m-%Y"),
        rows=table_rows,
        top_up=top_up,
        top_down=top_down,
        portfolio_alerts=portfolio_alerts,
        market_opportunities=market_opportunities[:8],
        avg_portfolio_return=avg_return,
        chart_labels=[r['name'][:20] for r in chart_rows],
        chart_values=[r['momentum'] for r in chart_rows]
    )

    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(output, encoding="utf-8")

if __name__ == "__main__": build_weekly()
