import json
from pathlib import Path
from datetime import datetime, timedelta
from jinja2 import Template

# Stier
ROOT = Path(__file__).resolve().parents[1]
HISTORY_FILE = ROOT / "data/history.json"
LATEST_FILE = ROOT / "data/latest.json"
TEMPLATE_FILE = ROOT / "templates/weekly.html.j2"
REPORT_FILE = ROOT / "build/weekly.html"

def get_ma(p, w): return sum(p[-w:]) / w if len(p) >= w else 0

def build_weekly():
    with open(HISTORY_FILE, "r") as f: history = json.load(f)
    with open(LATEST_FILE, "r", encoding="utf-8") as f: latest_list = json.load(f)
    
    rows = []
    portfolio_alerts = []
    
    for isin, prices_dict in history.items():
        dates = sorted(prices_dict.keys())
        if len(dates) < 200: continue
        
        all_p = [prices_dict[d] for d in dates]
        curr_p = all_p[-1]
        
        # Beregn nuværende og historisk (7 dage siden) trend
        curr_ma200 = get_ma(all_p, 200)
        curr_state = "BULL" if curr_p > curr_ma200 else "BEAR"
        
        past_idx = max(0, len(all_p) - 7)
        past_p = all_p[past_idx]
        past_ma200 = get_ma(all_p[:past_idx+1], 200)
        past_state = "BULL" if past_p > past_ma200 else "BEAR"
        
        # Trend Shift Logik
        shift = None
        if past_state == "BEAR" and curr_state == "BULL": shift = "UP"
        elif past_state == "BULL" and curr_state == "BEAR": shift = "DOWN"
        
        rows.append({
            "name": isin, # Navne-mapping sker her
            "trend_state": curr_state,
            "trend_shift": shift,
            "momentum": round(((curr_p - curr_ma200) / curr_ma200) * 100, 2),
            "drawdown": round(((curr_p - max(all_p)) / max(all_p)) * 100, 2),
            "week_change_pct": ((curr_p - past_p) / past_p) * 100
        })

    # Render... (som før, men med alle variabler tilgængelige)
