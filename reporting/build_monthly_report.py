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

BENCHMARK_ISIN = "PFA000002735" # PFA Aktier (Stedfortræder for Profil Høj)

def build_monthly():
    if not DATA_FILE.exists() or not HISTORY_FILE.exists():
        print("FEJL: Datafiler mangler.")
        return

    # 1. HENT DATA
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            latest_list = json.load(f)
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)
    except Exception as e:
        print(f"Fejl ved indlæsning af data: {e}")
        return

    latest_map = {item['isin']: item for item in latest_list}
    timestamp = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    active_rows = []
    sold_rows = []
    active_returns_total = []

    # 2. BEHANDL PORTEFØLJE-FONDE
    for isin, p_info in portfolio.items():
        if isin not in latest_map:
            continue
        
        official = latest_map[isin]
        curr_p = official['nav']
        buy_p = p_info.get('buy_price')
        
        total_return = ((curr_p - buy_p) / buy_p * 100) if buy_p else 0
        
        fund_data = {
            "isin": isin,
            "name": p_info.get('name', isin),
            "buy_date": p_info.get('buy_date', 'Ukendt'),
            "buy_price": buy_p,
            "curr_price": curr_p,
            "return_1m": official.get('return_1m', 0),
            "total_return": total_return,
            "is_active": p_info.get('active', True)
        }

        if fund_data['is_active']:
            active_rows.append(fund_data)
            active_returns_total.append(total_return)
        else:
            fund_data["sell_date"] = p_info.get('sell_date', 'Ukendt')
            sold_rows.append(fund_data)

    # 3. FIND TOP 5 MARKEDSMULIGHEDER (Fonde man ikke ejer aktivt)
    all_market_funds = []
    for item in latest_list:
        isin = item['isin']
        is_owned = isin in portfolio and portfolio[isin].get('active', False)
        
        if not is_owned:
            all_market_funds.append({
                "name": item.get('name', isin),
                "return_1m": item.get('return_1m', 0),
                "return_ytd": item.get('return_ytd', 0)
            })
    
    market_opps = sorted(all_market_funds, key=lambda x: x['return_1m'], reverse=True)[:5]

    # 4. BENCHMARK BEREGNING
    benchmark_return = 0
    if BENCHMARK_ISIN in latest_map:
        benchmark_return = latest_map[BENCHMARK_ISIN].get('return_1m', 0)

    # 5. RENDER HTML RAPPORT
    if TEMPLATE_FILE.exists():
        template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
        
        avg_port_return = sum(active_returns_total) / len(active_returns_total) if active_returns_total else 0
        
        html_output = template.render(
            timestamp=timestamp,
            active_funds=sorted(active_rows, key=lambda x: x['total_return'], reverse=True),
            sold_funds=sorted(sold_rows, key=lambda x: x['total_return'], reverse=True),
            market_opps=market_opps,
            benchmark_name="PFA Aktier",
            benchmark_return=benchmark_return,
            avg_portfolio_return=avg_port_return,
            diff_to_benchmark=avg_port_return - benchmark_return
        )
        
        REPORT_FILE.parent.mkdir(exist_ok=True)
        REPORT_FILE.write_text(html_output, encoding="utf-8")
        print(f"Monthly Rapport færdig med 'Sidste 1M %' sammenligning.")
    else:
        print(f"FEJL: Template mangler.")

if __name__ == "__main__":
    build_monthly()
