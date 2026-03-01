import json
import os
from pathlib import Path
from datetime import datetime, timedelta
from pfa import parse_pfa_from_text

ROOT = Path(__file__).resolve().parents[1]
TEXT_DIR = ROOT / "build/text"
OUT_FILE = ROOT / "data/latest.json"
HISTORY_FILE = ROOT / "data/history.json"
CONFIG_FILE = ROOT / "config/pfa_pdfs.json"

def calculate_backfill(nav, nav_date_str, returns):
    backfill = {}
    try:
        current_date = datetime.strptime(nav_date_str, '%Y-%m-%d')
    except:
        current_date = datetime.now()

    # Intervaller for at skabe historik til MA20, MA50 og MA200
    intervals = {
        '1w': 7, '1m': 30, '2m': 60, '3m': 91, 
        '6m': 182, '9m': 273, '1y': 365
    }

    for key, days in intervals.items():
        pct = returns.get(f'return_{key}')
        if pct is not None and isinstance(pct, (int, float)):
            # Baglæns regning: Pris = Nu kurs / (1 + afkast_procent)
            hist_price = nav / (1 + (pct / 100))
            hist_date = (current_date - timedelta(days=days)).strftime('%Y-%m-%d')
            backfill[hist_date] = round(hist_price, 2)
    return backfill

def main():
    if not CONFIG_FILE.exists(): 
        print(f"❌ Config fil mangler: {CONFIG_FILE}")
        return
        
    with open(CONFIG_FILE, "r") as f:
        isins = json.load(f)

    active_isins = [i.strip() for i in isins if not i.strip().startswith(("#", "-"))]
    results = []
    
    history = {}
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r") as f:
                history = json.load(f)
        except: 
            history = {}

    for isin in active_isins:
        txt_file = TEXT_DIR / f"{isin}.txt"
        data = {"isin": isin, "name": "Mangler data", "nav": None, "nav_date": None}
        
        if txt_file.exists():
            text = txt_file.read_text(encoding="utf-8", errors="ignore")
            parsed = parse_pfa_from_text(isin, text)
            data.update(parsed) 
            
            if data["nav"] and data["nav_date"]:
                if isin not in history: history[isin] = {}
                
                # --- ROBUST FEJL-TJEKKER (Volatility Guard) ---
                # Sænket til 5% (0.05) for at fange "ghost data" som i Magna
                dates = sorted(history[isin].keys())
                if dates:
                    last_date = dates[-1]
                    last_nav = history[isin][last_date]
                    diff = abs((data["nav"] - last_nav) / last_nav)
                    
                    if diff > 0.05: 
                        print(f"⚠️ Mistænkeligt hop i {isin}: {last_nav} -> {data['nav']} (Ignoreret for at beskytte historik)")
                        continue 

                # --- GEM KUN NYE DATA ---
                if data["nav_date"] not in history[isin]:
                    history[isin][data["nav_date"]] = data["nav"]
                
                # Backfill (Udfylder huller bagud i tid baseret på officielle afkast)
                historical_points = calculate_backfill(data["nav"], data["nav_date"], data)
                for h_date, h_nav in historical_points.items():
                    # Vigtigt: Overskriv aldrig eksisterende data med backfill-estimater
                    if h_date not in history[isin]:
                        history[isin][h_date] = h_nav
        
        results.append(data)

    # Gem og ryd op
    OUT_FILE.parent.mkdir(exist_ok=True)
    for isin in history:
        history[isin] = dict(sorted(history[isin].items()))
    
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

    print("✅ Main færdig: Historik opdateret og vasket for ekstreme udsving.")

if __name__ == "__main__":
    main()
