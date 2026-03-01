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

def get_momentum_status(f):
    """
    Beregner om fonden taber fart.
    Sammenligner sidste måneds afkast (1M) med gennemsnittet af de sidste 3 måneder.
    """
    r1m = f.get('return_1m', 0)
    r3m = f.get('return_3m', 0)
    
    # Vi tjekker kun momentum, hvis der er et positivt 3-måneders afkast at måle mod
    if r3m and r3m > 0:
        avg_monthly_speed = r3m / 3
        
        # Hvis det nuværende afkast er under 35% af det normale snit = "Fladet ud"
        if r1m < (avg_monthly_speed * 0.35):
            return "🛑 Fladet ud", "momentum-flat"
        
        # Hvis det er under 80% af det normale snit = "Slower"
        if r1m < (avg_monthly_speed * 0.80):
            return "⚠️ Slower", "momentum-slow"
        
        # Hvis det er 30% højere end snittet = "Accelererer"
        if r1m > (avg_monthly_speed * 1.30):
            return "🚀 Accelererer", "momentum-fast"
            
    # Standard status hvis alt følger normalen eller mangler 3M data
    if r1m > 0.5:
        return "✅ Stabil", "momentum-stable"
    
    return "➖ Neutral", "momentum-stable"

def validate_data(latest_map, portfolio):
    """Tjekker om nødvendige data er tilstede for beregningerne."""
    warnings = []
    
    # Tjek om benchmark findes
    if BENCHMARK_ISIN not in latest_map:
        warnings.append(f"ADVARSEL: Benchmark ISIN {BENCHMARK_ISIN} mangler i data.")

    # Tjek portefølje-data for aktive fonde
    for isin, p_info in portfolio.items():
        if p_info.get('active', True):
            if isin not in latest_map:
                warnings.append(f"ADVARSEL: Aktiv fond {isin} mangler i PFA-data (latest.json).")
            if 'buy_price' not in p_info or p_info['buy_price'] <= 0:
                warnings.append(f"ADVARSEL: Købspris mangler eller er 0 for {p_info.get('name', isin)}.")
    
    return warnings

def build_monthly():
    if not DATA_FILE.exists() or not PORTFOLIO_FILE.exists():
        print("KRITISK FEJL: Data- eller porteføljefil mangler.")
        return

    # 1. INDLÆS DATA
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            latest_list = json.load(f)
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)
    except Exception as e:
        print(f"Fejl ved indlæsning: {e}")
        return

    latest_map = {item['isin']: item for item in latest_list}
    
    # 2. VALIDERING
    validation_warnings = validate_data(latest_map, portfolio)
    for w in validation_warnings:
        print(w)

    timestamp = datetime.now().strftime('%d-%m-%Y %H:%M')
    active_rows = []
    sold_rows = []
    active_returns_total = []

    # 3. BEHANDL FONDE I PORTEFØLJEN
    for isin, p_info in portfolio.items():
        if isin not in latest_map:
            continue
        
        official = latest_map[isin]
        curr_p = official['nav']
        buy_p = p_info.get('buy_price', 0)
        
        # Beregn totalt afkast siden køb
        total_return = ((curr_p - buy_p) / buy_p * 100) if buy_p > 0 else 0
        
        # Hent Momentum status (Trafiklys)
        m_label, m_class = get_momentum_status(official)
        
        fund_data = {
            "name": p_info.get('name', isin),
            "buy_date": p_info.get('buy_date', 'N/A'),
            "buy_price": buy_p,
            "curr_price": curr_p,
            "return_1w": official.get('return_1w', 0),
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
            # Håndtering af historiske/solgte fonde
            fund_data["sell_date"] = p_info.get('sell_date', 'N/A')
            sold_rows.append(fund_data)

    # 4. FIND TOP 5 MARKEDSMULIGHEDER (Fonde man ikke ejer)
    market_opps = sorted([
        {
            "name": i.get('name', i['isin']), 
            "return_1m": i.get('return_1m', 0), 
            "return_ytd": i.get('return_ytd', 0)
        }
        for i in latest_list 
        if i['isin'] not in portfolio or not portfolio[i['isin']].get('active', False)
    ], key=lambda x: x['return_1m'], reverse=True)[:5]

    # 5. BENCHMARK OG STATISTIK
    benchmark_return = latest_map[BENCHMARK_ISIN].get('return_1m', 0) if BENCHMARK_ISIN in latest_map else 0
    avg_port_return = sum(active_returns_total) / len(active_returns_total) if active_returns_total else 0

    # 6. GENERER HTML RAPPORT
    if TEMPLATE_FILE.exists():
        template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
        
        html_output = template.render(
            timestamp=timestamp,
            active_funds=sorted(active_rows, key=lambda x: x['total_return'], reverse=True),
            sold_funds=sold_rows,
            market_opps=market_opps,
            benchmark_name="PFA Aktier",
            benchmark_return=benchmark_return,
            avg_portfolio_return=avg_port_return,
            diff_to_benchmark=avg_port_return - benchmark_return,
            warnings=validation_warnings
        )
        
        # Gem filen
        REPORT_FILE.parent.mkdir(exist_ok=True)
        REPORT_FILE.write_text(html_output, encoding="utf-8")
        print(f"✅ Månedsrapport færdig: build/monthly.html")
        print(f"ℹ️ {len(active_rows)} aktive positioner med momentum-analyse.")
    else:
        print(f"❌ FEJL: Template fil ikke fundet på {TEMPLATE_FILE}")

if __name__ == "__main__":
    build_monthly()
