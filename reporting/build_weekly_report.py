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
    """Beregner Moving Average. Håndterer vinduer mindre end historikken."""
    if not prices:
        return None
    actual_window = min(len(prices), window)
    relevant = prices[-actual_window:]
    return sum(relevant) / len(relevant)

def build_weekly():
    # 1. Dataindlæsning med sikkerhedsnet
    # Vi kræver history og portfolio. latest.json er valgfri for at øge robustheden.
    if not HISTORY_FILE.exists() or not PORTFOLIO_FILE.exists():
        print(f"FEJL: Kritiske filer mangler. Tjek {HISTORY_FILE} og {PORTFOLIO_FILE}")
        return

    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            portfolio = json.load(f)
        
        latest_list = []
        if LATEST_FILE.exists():
            with open(LATEST_FILE, "r", encoding="utf-8") as f:
                latest_list = json.load(f)
    except Exception as e:
        print(f"FEJL ved læsning af JSON: {e}")
        return

    # 2. Forberedelse af opslagsværker
    latest_map = {item['isin']: item for item in latest_list}
    
    # Find rapportens dato: Vi tager den nyeste dato fra seneste scraper-kørsel
    # Hvis den mangler, bruger vi dags dato.
    if latest_list:
        date_str = latest_list[0].get('nav_date', datetime.now().strftime("%Y-%m-%d"))
    else:
        date_str = datetime.now().strftime("%Y-%m-%d")
        
    week_num = datetime.strptime(date_str, "%Y-%m-%d").isocalendar()[1]

    rows = []
    active_returns = []
    portfolio_alerts = []
    market_opportunities = []

    # 3. Iteration over alle fonde fundet i historikken
    # Dette gør koden robust: Den ser alt hvad du har data på, uanset lister.
    for isin, price_dict in history.items():
        # Sorter datoer så vi er sikre på rækkefølgen
        sorted_dates = sorted(price_dict.keys())
        if not sorted_dates:
            continue
            
        all_prices = [price_dict[d] for d in sorted_dates]
        curr_p = all_prices[-1] # Den absolut nyeste pris i historikken
        
        # Hent metadata (Navn, porteføljestatus)
        # Vi tjekker porteføljen først, da det er her du navngiver dine handler
        port_info = portfolio.get(isin, {})
        official = latest_map.get(isin, {})
        
        fund_name = port_info.get('name') or official.get('name', isin)
        is_active = port_info.get('active', False)
        buy_p = port_info.get('buy_price')

        # 4. Beregn nøgletal (Robust logik)
        # Hvis return_1w mangler i latest.json, beregner vi det selv fra historikken
        week_chg = official.get('return_1w')
        if week_chg is None:
            if len(all_prices) >= 5:
                # Estimering: Sidste pris vs prisen for 5 datapunkter siden
                prev_p = all_prices[-5]
                week_chg = ((curr_p - prev_p) / prev_p) * 100 if prev_p else 0
            else:
                week_chg = 0.0

        ytd_chg = official.get('return_ytd', 0)

        # Trend & Momentum (MA200)
        ma200 = get_ma(all_prices, 200)
        curr_state = "UP" if ma200 and curr_p > ma200 else "DOWN"
        
        # Shift detection (Sammenlign nyeste og næstnyeste datapunkt)
        past_state = "DOWN"
        if len(all_prices) > 1:
            past_p = all_prices[-2]
            # MA200 eksklusiv sidste punkt
            past_ma200 = get_ma(all_prices[:-1], 200)
            past_state = "UP" if past_ma200 and past_p > past_ma200 else "DOWN"

        # 5. Portefølje Logik & Gevinst
        total_return = None
        if is_active:
            active_returns.append(week_chg)
            if buy_p:
                total_return = ((curr_p - buy_p) / buy_p) * 100
            
            # Alarmer ved trendskift for aktive fonde
            if past_state == "DOWN" and curr_state == "UP":
                portfolio_alerts.append({"name": fund_name, "msg": "🚀 Trend skiftet til BULL (KØB)"})
            elif past_state == "UP" and curr_state == "DOWN":
                portfolio_alerts.append({"name": fund_name, "msg": "⚠️ Trend skiftet til BEAR (SÆLG)"})
        
        # Markedsmulighed hvis ikke aktiv, men trend skifter op
        elif past_state == "DOWN" and curr_state == "UP":
            market_opportunities.append({"name": fund_name})

        # Momentum score & Drawdown
        momentum = round(((curr_p - ma200) / ma200 * 100), 1) if ma200 else 0
        ath = max(all_prices)
        drawdown = ((curr_p - ath) / ath * 100) if ath > 0 else 0

        rows.append({
            "isin": isin,
            "name": fund_name, 
            "is_active": is_active, 
            "week_change_pct": week_chg,
            "total_return": total_return,
            "trend_state": curr_state, 
            "momentum": momentum,
            "ytd_return": ytd_chg, 
            "drawdown": drawdown
        })

    # 6. Sortering og Top-lister
    # Top 10 momentum til grafen
    sorted_momentum = sorted(rows, key=lambda x: x['momentum'], reverse=True)[:10]
    chart_labels = [r['name'][:20] for r in sorted_momentum]
    chart_values = [r['momentum'] for r in sorted_momentum]

    # 7. Render Template
    if not TEMPLATE_FILE.exists():
        print(f"FEJL: Template-filen mangler på {TEMPLATE_FILE}")
        return

    template = Template(TEMPLATE_FILE.read_text(encoding="utf-8"))
    html_output = template.render(
        report_date=date_str,
        week_number=week_num,
        avg_portfolio_return=sum(active_returns)/len(active_returns) if active_returns else 0,
        portfolio_alerts=portfolio_alerts,
        market_opportunities=market_opportunities[:8],
        top_up=sorted(rows, key=lambda x: x['week_change_pct'], reverse=True)[:5],
        top_down=sorted(rows, key=lambda x: x['week_change_pct'])[:5],
        # Tabel sortering: Aktive først, derefter momentum
        rows=sorted(rows, key=lambda x: (not x['is_active'], -x['momentum'])),
        chart_labels=chart_labels,
        chart_values=chart_values
    )

    # 8. Gem rapport
    REPORT_FILE.parent.mkdir(exist_ok=True)
    REPORT_FILE.write_text(html_output, encoding="utf-8")
    
    print(f"--- Rapport Genereret ---")
    print(f"Dato: {date_str} (Uge {week_num})")
    print(f"Antal fonde i alt: {len(rows)}")
    print(f"Aktive fonde fundet: {len(active_returns)}")
    print(f"Gemt som: {REPORT_FILE}")

if __name__ == "__main__":
    build_weekly()
