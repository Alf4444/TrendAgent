import json
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# ==========================================
# KONFIGURATION & STIER
# ==========================================
ROOT = Path(__file__).resolve().parents[1]
HISTORY_FILE = ROOT / "data/history.json"
LATEST_FILE = ROOT / "data/latest.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
TEMPLATE_FILE = ROOT / "templates/weekly.html.j2"
REPORT_FILE = ROOT / "build/weekly.html"

def get_ma(prices, window):
    if not prices: return None
    actual_window = min(len(prices), window)
    relevant = prices[-actual_window:]
    return sum(relevant) / len(relevant)

def build_weekly():
    # 1. Hent rådata
    if not HISTORY_FILE.exists() or not LATEST_FILE.exists():
        print("FEJL: Datafiler mangler.")
        return

    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        history = json.load(f)
    with open(LATEST_FILE, "r", encoding="utf-8") as f:
        latest_list = json.load(f)
    with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
        portfolio = json.load(f)

    # 2. Skab et opslagsværk fra latest.json
    latest_map = {item['isin']: item for item in latest_list}
    
    now = datetime.now()
    date_str = latest_list[0]['nav_date'] if latest_list else now.strftime("%Y-%m-%d")
    week_num = datetime.strptime(date_str, "%Y-%m-%d").isocalendar()[1]

    rows = []
    active_returns = []
    portfolio_alerts = []
    market_opportunities = []

    for isin, price_dict in history.items():
        if isin not in latest_map: continue
        
        official = latest_map[isin]
        curr_p = official['nav']
        week_chg = official.get('return_1w', 0)
        ytd_chg = official.get('return_ytd', 0)
        fund_name = official.get('name', isin)

        # Beregn Trend baseret på historik
        dates = sorted(price_dict.keys())
        all_prices = [price_dict[d] for d in dates]
        ma200 = get_ma(all_prices, 200)
        
        curr_state = "UP" if ma200 and curr_p > ma200 else "DOWN"
        
        # Shift detection (VIGTIG LOGIK GENOPRETTET)
        past_state = "DOWN"
        if len(all_prices) > 1:
            past_p = all_prices[-2]
            past_ma200 = get_ma(all_prices[:-1], 200)
            past_state = "UP" if past_ma200 and past_p > past_ma200 else "DOWN"

        # Portfolio data & Gevinstberegning
        port_info = portfolio.get(isin, {})
        is_active = port_info.get('active', False)
        buy_p = port_info.get('buy_price')
        
        total_return = None
        if is_active and buy_p:
            total_return = ((curr_p - buy_p) / buy_p) * 100

        if is_active:
            active_returns.append(week_chg)
            if past_state == "DOWN" and curr_state == "UP":
                portfolio_alerts.append({"name": fund_name, "msg": "🚀 Trend skiftet til BULL (KØB)"})
            elif past_state == "UP" and curr_state == "DOWN":
                portfolio_alerts.append({"name": fund_name, "msg": "⚠️ Trend skiftet til BEAR (SÆLG)"})
        elif past_state == "DOWN" and curr_state == "UP":
            market_opportunities.append({"name": fund_name})

        # Momentum & Risk
        momentum = round(((curr_p - ma200) / ma200 * 100), 1) if ma200 else 0
        ath = max(all_prices) if all_prices else curr_p
        drawdown = ((curr_p - ath) / ath * 100) if ath > 0 else 0

        rows.append({
            "name": fund_name, 
            "is_active": is_active, 
            "week_change_pct": week_chg,
            "total_return": total_return,
            "trend_state": curr_state, 
            "momentum": momentum,
            "ytd_return": ytd_chg, 
            "drawdown": drawdown
        })

    # Data til grafen
    sorted_momentum = sorted(rows, key=lambda x: x['momentum'], reverse=True)[:10]
    chart_labels = [r['name'][:20] for r in sorted_momentum]
    chart_values = [r['momentum'] for r in sorted_momentum]

    # Render Template
    template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
    html_output = template.render(
        report_date=date_str,
        week_number=week_num,
        avg_portfolio_return=sum(active_returns)/len(active_returns) if active_returns else 0,
        portfolio_alerts=portfolio_alerts,
        market_opportunities=market_opportunities[:8],
        top_up=sorted(rows, key=lambda x: x['week_change_pct'], reverse=True)[:5],
        top_down=sorted(rows, key=lambda x: x['week_change_pct'])[:5],
        rows=sorted(rows, key=lambda x: (not x['is_active'], -x['momentum'])),
        chart_labels=chart_labels,
        chart_values=chart_values
    )

    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_output, encoding="utf-8")
    print(f"Weekly Rapport færdig. {len(rows)} fonde opdateret.")

if __name__ == "__main__":
    build_weekly()
