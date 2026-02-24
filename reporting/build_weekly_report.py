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

def calculate_ma(prices, window=200):
    if not prices or len(prices) < 5: return 0
    relevant = prices[-window:]
    return sum(relevant) / len(relevant)

def build_weekly():
    if not HISTORY_FILE.exists() or not LATEST_FILE.exists():
        print("Data mangler...")
        return

    with open(HISTORY_FILE, "r") as f:
        history = json.load(f)
    with open(LATEST_FILE, "r", encoding="utf-8") as f:
        latest_list = json.load(f)
    
    portfolio = {}
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE, "r") as f:
            portfolio = json.load(f)

    names_map = {i['isin']: i.get('name', i['isin']) for i in latest_list}
    latest_map = {i['isin']: i for i in latest_list}

    rows = []
    today = datetime.now()
    
    for isin, prices_dict in history.items():
        dates = sorted(prices_dict.keys())
        if len(dates) < 2: continue
        
        curr_nav = prices_dict[dates[-1]]
        target_date_obj = datetime.strptime(dates[-1], "%Y-%m-%d") - timedelta(days=7)
        past_date = min(dates, key=lambda d: abs((datetime.strptime(d, "%Y-%m-%d") - target_date_obj).days))
        past_nav = prices_dict[past_date]
        
        all_prices = [prices_dict[d] for d in dates]
        ma200 = calculate_ma(all_prices, 200)
        momentum = ((curr_nav - ma200) / ma200 * 100) if ma200 > 0 else 0
        
        rows.append({
            "isin": isin,
            "name": names_map.get(isin, isin),
            "is_active": portfolio.get(isin, {}).get('active', False),
            "week_change_pct": ((curr_nav - past_nav) / past_nav * 100) if past_nav else 0,
            "trend_state": "UP" if curr_nav > ma200 else "DOWN",
            "momentum": round(momentum, 2),
            "ytd_return": float(str(latest_map.get(isin, {}).get('return_ytd', 0)).replace(',', '.')),
            "drawdown": ((curr_nav - max(all_prices)) / max(all_prices) * 100) if max(all_prices) > 0 else 0
        })

    # 1. Sortering til tabellen: Dine fonde først
    table_rows = sorted(rows, key=lambda x: (not x['is_active'], -x['momentum']))

    # 2. Top lister (Uafhængigt af hvad du ejer)
    top_up = sorted(rows, key=lambda x: x['week_change_pct'], reverse=True)[:5]
    top_down = sorted(rows, key=lambda x: x['week_change_pct'])[:5]

    # 3. Data til graf (Dine aktive fonde)
    chart_rows = [r for r in table_rows if r['is_active']]
    if not chart_rows: chart_rows = table_rows[:8]
    
    chart_labels = [r['name'][:20] for r in chart_rows]
    chart_values = [r['momentum'] for r in chart_rows]

    # Render Template
    template_html = TEMPLATE_FILE.read_text(encoding="utf-8")
    output = Template(template_html).render(
        week_label=today.strftime("%V"),
        week_end_date=today.strftime("%d-%m-%Y"),
        rows=table_rows,
        top_up=top_up,
        top_down=top_down,
        chart_labels=chart_labels,
        chart_values=chart_values
    )

    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(output, encoding="utf-8")
    print("Ugerapport med graf og Top 5 er klar!")

if __name__ == "__main__":
    build_weekly()
