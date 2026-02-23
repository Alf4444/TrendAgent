import json
import os
from pathlib import Path
from datetime import datetime, timedelta
# Importér din PFA parser-logik
from pfa import parse_pfa_from_text

# Stier defineret ud fra projektets rod
ROOT = Path(__file__).resolve().parents[1]
TEXT_DIR = ROOT / "build/text"
OUT_FILE = ROOT / "data/latest.json"
HISTORY_FILE = ROOT / "data/history.json"
CONFIG_FILE = ROOT / "config/pfa_pdfs.json"

def calculate_backfill(nav, nav_date_str, returns):
    """
    Beregner historiske kurser baseret på afkast-procenter fra faktaarket.
    Dette giver robotten 'hukommelse' med det samme.
    """
    backfill = {}
    try:
        current_date = datetime.strptime(nav_date_str, '%Y-%m-%d')
    except:
        current_date = datetime.now()

    # Intervaller defineret i dage (standard for finansiel rapportering)
    intervals = {
        '1w': 7,
        '1m': 30,
        '3m': 91,
        '6m': 182,
        '1y': 365
    }

    for key, days in intervals.items():
        pct = returns.get(f'return_{key}')
        # Vi tjekker om pct er et tal (float/int) og ikke None eller "-"
        if pct is not None and isinstance(pct, (int, float)):
            # Formel: Gammel_kurs = Ny_kurs / (1 + (pct/100))
            hist_price = nav / (1 + (pct / 100))
            hist_date = (current_date - timedelta(days=days)).strftime('%Y-%m-%d')
            backfill[hist_date] = round(hist_price, 2)
            
    return backfill

def main():
    if not CONFIG_FILE.exists(): 
        print(f"Fejl: Fandt ikke {CONFIG_FILE}")
        return

    with open(CONFIG_FILE, "r") as f:
        isins = json.load(f)

    # Filtrér inaktive ISINs fra (dem med # eller -)
    active_isins = [i.strip() for i in isins if not i.strip().startswith(("#", "-"))]
    results = []
    
    # Indlæs eksisterende historik
    history = {}
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r") as f:
                history = json.load(f)
        except: 
            history = {}

    for isin in active_isins:
        txt_file = TEXT_DIR / f"{isin}.txt"
        
        # Basis-objekt hvis parsing fejler
        data = {
            "isin": isin,
            "url": f"https://pfapension.os.fundconnect.com/api/v1/public/printer/solutions/default/factsheet?language=da-DK&isin={isin}",
            "name": "Mangler data",
            "nav": None,
            "nav_date": None,
            "return_1w": None,
            "return_1m": None,
            "return_3m": None,
            "return_6m": None,
            "return_1y": None,
            "return_ytd": None
        }
        
        if txt_file.exists():
            text = txt_file.read_text(encoding="utf-8", errors="ignore")
            parsed = parse_pfa_from_text(isin, text)
            data.update(parsed) # Fyld data op med de rigtige tal
            
            # --- BACKFILL & HISTORIK LOGIK ---
            if data["nav"] and data["nav_date"]:
                if isin not in history: 
                    history[isin] = {}
                
                # 1. Gem den dagsaktuelle kurs
                history[isin][data["nav_date"]] = data["nav"]
                
                # 2. Beregn og gem de historiske 'tidsmaskine' punkter
                historical_points = calculate_backfill(data["nav"], data["nav_date"], data)
                for h_date, h_nav in historical_points.items():
                    # Vi overskriver ALDRIG eksisterende (rigtig) logget data med backfill
                    if h_date not in history[isin]:
                        history[isin][h_date] = h_nav
        
        results.append(data)

    # --- GEM DATA ---
    OUT_FILE.parent.mkdir(exist_ok=True)
    
    # Sorter historikken kronologisk for hver fond (vigtigt for MA-beregning)
    for isin in history:
        history[isin] = dict(sorted(history[isin].items()))
    
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
        
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

    print(f"Parsing færdig. Historik og backfill gemt for {len(results)} fonde.")

if __name__ == "__main__":
    main()
