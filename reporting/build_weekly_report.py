import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from jinja2 import Template

ROOT = Path(__file__).resolve().parents[1]
HISTORY_FILE = ROOT / "data/history.json"
LATEST_FILE = ROOT / "data/latest.json"
TEMPLATE_FILE = ROOT / "templates/weekly.html.j2"
REPORT_FILE = ROOT / "build/weekly.html"

def calculate_ma(prices, window=200):
    if len(prices) < 2: return 0
    relevant = prices[-window:]
    return sum(relevant) / len(relevant)

def build_weekly():
    if not HISTORY_FILE.exists() or not TEMPLATE_FILE.exists():
        print("Fejl: Mangler historik eller template fil.")
        return

    with open(HISTORY_FILE, "r") as f:
        history = json.load(f)
    with open(LATEST_FILE, "r", encoding="utf-8") as f:
        latest_data = {item['isin']: item for item in json.load(f)}

    rows = []
    today = datetime.now()
    week_label = today.strftime("%V") # Ugenummer
    week_end_date = today.strftime("%d-%m-%Y")

    for isin, prices_dict in history.items():
        # Sorter datoer for at finde nuværende og for 7 dage siden
        dates = sorted(prices_dict.keys())
        if len(dates) < 2: continue
        
        current_nav = prices_dict[dates[-1]]
        
        # Find kurs for ca. 7 dage siden (eller tætteste match)
        seven_days_ago = (datetime.strptime(dates[-1], "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        # Find den dato i historikken der er tættest på seven_days_ago
        past_date = min(dates, key=lambda d: abs((datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(seven_days_ago, "%Y-%m-%d")).days))
        past_nav = prices_dict[past_date]
        
        # Beregninger
        week_change = ((current_nav - past_nav) / past_nav * 100) if past_nav else 0
        
        # Trend State (UP/DOWN) baseret på MA200
        all_prices = [prices_dict[d] for d in dates]
        ma200 = calculate_ma(all_prices, 200)
        trend_state = "UP" if current_nav > ma200 else "DOWN"
        
        # Drawdown
        ath = max(all_prices)
        drawdown = ((current_nav - ath) / ath * 100) if ath > 0 else 0
        
        # YTD (Hent fra latest.json hvis muligt, ellers beregn)
        ytd = latest_data.get(isin, {}).get('return_ytd', 0)
        if isinstance(ytd, str): ytd = float(ytd.replace(',', '.'))

        rows.append({
            "isin": isin,
            "week_change_pct": week_change,
            "trend_state": trend_state,
            "ytd_return": ytd,
            "drawdown": drawdown
        })

    # Sortering til Top 5 lister
    top_up = sorted(rows, key=lambda x: x['week_change_pct'], reverse=True)[:5]
    top_down = sorted(rows, key=lambda x: x['week_change_pct'])[:5]

    # Render Template
    template_html = TEMPLATE_FILE.read_text(encoding="utf-8")
    jinja_template = Template(template_html)
    
    output = jinja_template.render(
        week_label=week_label,
        week_end_date=week_end_date,
        rows=rows,
        top_up=top_up,
        top_down=top_down
    )

    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(output, encoding="utf-8")
    print(f"Ugerapport for uge {week_label} er genereret!")

if __name__ == "__main__":
    build_weekly()
