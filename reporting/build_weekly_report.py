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

def get_ma(prices, window):
    if not prices or len(prices) < window: return None
    relevant = prices[-window:]
    return sum(relevant) / len(relevant)

def build_weekly():
    if not HISTORY_FILE.exists() or not LATEST_FILE.exists():
        print("Fejl: Datafiler mangler.")
        return

    with open(HISTORY_FILE, "r") as f:
        history = json.load(f)
    with open(LATEST_FILE, "r", encoding="utf-8") as f:
        latest_data = json.load(f)
    with open(PORTFOLIO_FILE, "r") as f:
        portfolio = json.load(f)

    # Map ISIN til Navne og YTD data
    names_map = {i['isin']: i.get('name', i['isin']) for i in latest_data}
    ytd_map = {i['isin']: i.get('return_ytd', 0) for i in latest_data}
    
    rows = []
    active_returns = []
    portfolio_alerts = []
    market_opportunities = []

    for isin, price_dict in history.items():
        # Sorter datoer og find priser
        dates = sorted(price_dict.keys())
        all_prices = [price_dict[d] for d in dates]
        
        if len(all_prices) < 200: continue

        curr_p = all_prices[-1]
        ma200 = get_ma(all_prices, 200)
        
        # --- 7-DAGES ANALYSE (Trend Shift & Change %) ---
        # Vi finder prisen for ca. 7 dage siden
        past_idx = max(0, len(all_prices) - 7)
        past_p = all_prices[past_idx]
        
        # Beregn trend-status nu vs da
        curr_state = "BULL" if curr_p > ma200 else "BEAR"
        
        # Beregn historisk MA200 for 7 dage siden for præcis trend_shift
        past_history = all_prices[:past_idx+1]
        past_ma200 = get_ma(past_history, 200) or ma200
        past_state = "BULL" if past_p > past_ma200 else "BEAR"
        
        # Detekter Shift
        shift = None
        if past_state == "BEAR" and curr_state == "BULL": shift = "UP"
        elif past_state == "BULL" and curr_state == "BEAR": shift = "DOWN"

        is_active = portfolio.get(isin, {}).get('active', False)
        fund_name = names_map.get(isin, isin)
        week_chg = ((curr_p - past_p) / past_p * 100)

        # Indsamling til alarmer
        if is_active:
            active_returns.append(week_chg)
            if shift == "UP":
                portfolio_alerts.append({"name": fund_name, "msg": "🚀 Skiftet til BULL", "type": "BULL"})
            elif shift == "DOWN":
                portfolio_alerts.append({"name": fund_name, "msg": "⚠️ Skiftet til BEAR", "type
