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
    # Sikkerhedstjek
    if not DATA_FILE.exists() or not HISTORY_FILE.exists():
        print("FEJL: Datafiler mangler.")
        return

    # 1. HENT DATA (Præcis som Daily/Weekly)
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

    # Skab opslagsværk fra latest
    latest_map = {item['isin']: item for item in latest_list}
    timestamp = datetime.now().strftime('%d-%m-%Y %H:%M')
    
    active_rows = []
    sold_rows = []
    active_returns = []

    # 2. BEHANDL FONDE
    for isin, p_info in portfolio.items():
        if isin not in latest_map:
            continue
        
        official = latest_map[isin]
        curr_p = official['nav']
        fund_name = p_info.get('name', isin)
        buy_p = p_info.get('buy_price')
        
        # Beregn afkast siden køb (Procentuelt)
        total_return = ((curr_p - buy_p) / buy_p * 100) if buy_p else 0
        
        fund_data = {
            "isin": isin,
            "name": fund_name,
            "buy_date": p_info.get('buy_date', 'Ukendt'),
            "buy_price": buy_p,
            "curr_price": curr_p,
            "total_return": total_return,
            "is_active": p_info.get('active', True)
        }

        if fund_data['is_active']:
            active_rows.append(fund_data)
            active_returns.append(total_return)
        else:
            fund_data["sell_date"] = p_info.get('sell_date', 'Ukendt')
            sold_rows.append(fund_data)

    # 3. BENCHMARK BEREGNING (PFA Aktier)
    benchmark_return = 0
    if BENCHMARK_ISIN in latest_map:
        # Her henter vi 1-måneds afkastet direkte fra PFA's egne data
        benchmark_return = latest_map[BENCHMARK_ISIN].get('return_1m', 0)

    # 4. RENDER HTML RAPPORT
    if TEMPLATE_FILE.exists():
        template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
        
        avg_port_return = sum(active_returns) / len(active_returns) if active_returns else 0
        
        html_output = template.render(
            timestamp=timestamp,
            active_funds=sorted(active_rows, key=lambda x: x['total_return'], reverse=True),
            sold_funds=sorted(sold_rows, key=lambda x: x['total_return'], reverse=True),
            benchmark_name="PFA Aktier (Profil Høj Proxy)",
            benchmark_return=benchmark_return,
            avg_portfolio_return=avg_port_return,
            diff_to_benchmark=avg_port_return - benchmark_return
        )
        
        REPORT_FILE.parent.mkdir(exist_ok=True)
        REPORT_FILE.write_text(html_output, encoding="utf-8")
        print(f"Monthly Rapport færdig: {len(active_rows)} aktive og {len(sold_rows)} solgte analyseret.")
    else:
        print(f"FEJL: Template mangler på {TEMPLATE_FILE}")

if __name__ == "__main__":
    build_monthly()
