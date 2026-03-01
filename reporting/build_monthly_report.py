import json
from pathlib import Path
from datetime import datetime
from jinja2 import Template

# ==========================================
# KONFIGURATION & ROBUSTE STIER
# ==========================================
ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = ROOT / "data/latest.json"
PORTFOLIO_FILE = ROOT / "config/portfolio.json"
TEMPLATE_FILE = ROOT / "templates/monthly.html.j2"
REPORT_FILE = ROOT / "build/monthly.html"

BENCHMARK_ISIN = "PFA000002735" # PFA Aktier (Proxy for Profil Høj)

def get_ranking_data(latest_list):
    """Sortér alle fonde efter 1M afkast og giv dem en plads (Rank)."""
    sorted_list = sorted(latest_list, key=lambda x: x.get('return_1m', -999), reverse=True)
    rank_map = {item['isin']: index + 1 for index, item in enumerate(sorted_list)}
    return rank_map, len(sorted_list)

def get_momentum_status(f, rank):
    """
    Beregner status baseret på Ranking-modellen (Relativ styrke).
    """
    r1m = f.get('return_1m', 0)
    
    # SALG: Hvis den er uden for Top 10 (Opportunity Cost)
    if rank > 10:
        return "🛑 Outperformed", "momentum-flat"
    
    # ADVARSEL: Hvis afkastet er negativt eller den er ved at glide ud af Top 5
    if r1m < 0 or rank > 5:
        return "⚠️ Slower", "momentum-slow"
    
    # KØB/HOLD: Top 5 og positivt afkast
    if rank <= 5 and r1m > 0:
        return "🚀 Top Performer", "momentum-fast"
    
    return "✅ Stabil", "momentum-stable"

def validate_data(latest_map, portfolio):
    warnings = []
    if BENCHMARK_ISIN not in latest_map:
        warnings.append(f"ADVARSEL: Benchmark ISIN {BENCHMARK_ISIN} mangler i data.")
    for isin, p_info in portfolio.items():
        if p_info.get('active', True) and isin not in latest_map:
            warnings.append(f"ADVARSEL: Aktiv fond {isin} mangler i PFA-data.")
    return warnings

def build_monthly():
    if not DATA_FILE.exists() or not PORTFOLIO_FILE.exists():
        print("KRITISK FEJL: Data- eller porteføljefil mangler.")
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            latest_list = json.load(f)
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)
    except Exception as e:
        print(f"Fejl ved indlæsning: {e}")
        return

    # 1. Beregn Ranking for hele markedet
    rank_map, total_market_count = get_ranking_data(latest_list)
    latest_map = {item['isin']: item for item in latest_list}
    validation_warnings = validate_data(latest_map, portfolio)

    now = datetime.now()
    timestamp = now.strftime('%d-%m-%Y %H:%M')
    week_number = now.strftime('%V')

    active_rows = []
    sold_rows = []
    active_returns_total = []

    # 2. Behandl Portefølje med Ranking-logik
    for isin, p_info in portfolio.items():
        if isin not in latest_map: continue
        
        official = latest_map[isin]
        rank = rank_map.get(isin, 99)
        curr_p = official['nav']
        buy_p = p_info.get('buy_price', 0)
        total_return = ((curr_p - buy_p) / buy_p * 100) if buy_p > 0 else 0
        
        m_label, m_class = get_momentum_status(official, rank)
        
        fund_data = {
            "isin": isin,
            "name": p_info.get('name', isin),
            "rank": rank,
            "buy_price": buy_p,
            "curr_price": curr_p,
            "return_1m": official.get('return_1m', 0),
            "momentum_label": m_label,
            "momentum_class": m_class,
            "total_return": total_return,
            "is_active": p_info.get('active', True)
        }

        if fund_data['is_active']:
            active_rows.append(fund_data)
            active_returns_total.append(total_return)
        else:
            fund_data["sell_date"] = p_info.get('sell_date', 'N/A')
            sold_rows.append(fund_data)

    # 3. Top 5 Muligheder (Altid de 5 bedste på markedet)
    market_opps = sorted([
        {
            "name": i.get('name', i['isin']), 
            "return_1m": i.get('return_1m', 0), 
            "return_ytd": i.get('return_ytd', 0),
            "rank": rank_map.get(i['isin'])
        }
        for i in latest_list 
    ], key=lambda x: x['return_1m'], reverse=True)[:5]

    # 4. Action Plan baseret på Ranking
    sell_signals = [f for f in active_rows if f['rank'] > 10]
    buy_signals = [o for o in market_opps if o['rank'] <= 3]

    benchmark_return = latest_map[BENCHMARK_ISIN].get('return_1m', 0) if BENCHMARK_ISIN in latest_map else 0
    avg_port_return = sum(active_returns_total) / len(active_returns_total) if active_returns_total else 0

    if TEMPLATE_FILE.exists():
        template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
        html_output = template.render(
            timestamp=timestamp,
            week_number=week_number,
            active_funds=sorted(active_rows, key=lambda x: x['rank']),
            sold_funds=sold_rows,
            market_opps=market_opps,
            sell_signals=sell_signals,
            buy_signals=buy_signals,
            benchmark_name="PFA Aktier",
            benchmark_return=benchmark_return,
            avg_portfolio_return=avg_port_return,
            diff_to_benchmark=avg_port_return - benchmark_return,
            warnings=validation_warnings,
            total_market_count=total_market_count
        )
        REPORT_FILE.parent.mkdir(exist_ok=True)
        REPORT_FILE.write_text(html_output, encoding="utf-8")
        print(f"✅ Ranking Rapport færdig (Uge {week_number}).")

if __name__ == "__main__":
    build_monthly()
