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
    if not prices: return 0
    relevant = prices[-window:]
    return sum(relevant) / len(relevant)

def build_weekly():
    # 1. Hent data
    if not HISTORY_FILE.exists() or not LATEST_FILE.exists():
        print("Fejl: Datafiler mangler.")
        return

    with open(HISTORY_FILE, "r") as f:
        history = json.load(f)
    with open(LATEST_FILE, "r", encoding="utf-8") as f:
        latest_list = json.load(f)
    
    # Valgfri: Hent portefølje hvis den findes
    portfolio = {}
    if PORTFOLIO_FILE.exists():
        with open(PORTFOLIO_FILE, "r") as f:
            portfolio = json.load(f)

    # Lav opslagsværk for navne og YTD
    names_map = {i['isin']: i.get('name', i['isin']) for i in latest_list}
    latest_map = {i['isin']: i for i in latest_list}

    rows = []
    today = datetime.now()
    
    for isin, prices_dict in history.items():
        dates = sorted(prices_dict.keys())
        if len(dates) < 2: continue
        
        curr_nav = prices_dict[dates[-1]]
        
        # Find kurs for 7 dage siden (eller tætteste match)
        target_date_obj = datetime.strptime(dates[-1], "%Y-%m-%d") - timedelta(days=7)
        past_date = min(dates, key=lambda d: abs((datetime.strptime(d, "%Y-%m-%d") - target_date_obj).days))
        past_nav = prices_dict[past_date]
        
        # Beregninger
        week_change = ((curr_nav - past_nav) / past_nav * 100) if past_nav else 0
        all_prices = [prices_dict[d] for d in dates]
        ma200 = calculate_ma(all_prices, 200)
        
        # Drawdown
        ath = max(all_prices)
        drawdown = ((curr_nav - ath) / ath * 100) if ath > 0 else 0
        
        # Ejerskab
        is_active = portfolio.get(isin, {}).get('active', False)

        rows.append({
            "isin": isin,
            "name": names_map.get(isin, isin),
            "is_active": is_active,
            "week_change_pct": week_change,
            "trend_state": "UP" if curr_nav > ma200 else "DOWN",
            "ytd_return": float(str(latest_map.get(isin, {}).get('return_ytd', 0)).replace(',', '.')),
            "drawdown": drawdown
        })

    # 2. Sortering: Eget ejerskab først, derefter højeste uge-afkast
    rows = sorted(rows, key=lambda x: (not x['is_active'], -x['week_change_pct']))

    # 3. Top lister (Top 5 uafhængig af ejerskab)
    top_up = sorted(rows, key=lambda x: x['week_change_pct'], reverse=True)[:5]
    top_down = sorted(rows, key=lambda x: x['week_change_pct'])[:5]

    # 4. Render Template
    if not TEMPLATE_FILE.exists():
        print("Fejl: Template mangler.")
        return

    template_html = TEMPLATE_FILE.read_text(encoding="utf-8")
    jinja_template = Template(template_html)
    
    output = jinja_template.render(
        week_label=today.strftime("%V"),
        week_end_date=today.strftime("%d-%m-%Y"),
        rows=rows,
        top_up=top_up,
        top_down=top_down
    )

    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(output, encoding="utf-8")
    print(f"Ugerapport færdig: build/weekly.html opdateret.")

if __name__ == "__main__":
    build_weekly()
