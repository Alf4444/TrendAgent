import json
from pathlib import Path
from datetime import datetime, timedelta

# Stier - vi finder ROOT baseret på filens placering
ROOT = Path(__file__).resolve().parent
HISTORY_FILE = ROOT / "data/history.json"
LATEST_FILE = ROOT / "data/latest.json"

def backfill_history():
    if not LATEST_FILE.exists():
        print(f"Fejl: Fandt ikke {LATEST_FILE}")
        return

    with open(LATEST_FILE, "r", encoding="utf-8") as f:
        latest_data = json.load(f)
    
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            history = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        history = {}

    print("Starter backfill baseret på officielle performance-tal...")

    for fund in latest_data:
        isin = fund['isin']
        nav_nu = fund['nav']
        
        # Vi skal bruge nav_date for at regne baglæns
        try:
            dato_nu = datetime.strptime(fund['nav_date'], "%Y-%m-%d")
        except:
            continue
        
        if isin not in history:
            history[isin] = {}

        # Definition af ankerpunkter (dage tilbage, nøgle i latest.json)
        # Vi bruger 7 dage (1w), 30 dage (1m), 90 dage (3m), 180 dage (6m) og 365 dage (1y)
        points = [
            (7, 'return_1w'),
            (30, 'return_1m'),
            (90, 'return_3m'),
            (180, 'return_6m'),
            (365, 'return_1y')
        ]

        # Gem den nuværende pris først
        history[isin][fund['nav_date']] = nav_nu

        for days, key in points:
            return_pct = fund.get(key)
            # Vi tjekker om tallet findes og ikke er 0 (for at undgå fejl)
            if return_pct is not None and return_pct != 0:
                past_date = (dato_nu - timedelta(days=days)).strftime("%Y-%m-%d")
                
                # Formel: GammelPris = NyPris / (1 + (Afkast/100))
                past_price = round(nav_nu / (1 + (return_pct / 100)), 2)
                
                # Vi skriver kun punktet, hvis det ikke allerede findes
                if past_date not in history[isin]:
                    history[isin][past_date] = past_price
                    print(f"Lagt i historik for {isin}: {past_date} = {past_price} ({key})")

    # Gem den opdaterede history.json
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)
    
    print("\nFærdig! Din history.json er nu fyldt ud med historiske ankerpunkter.")

if __name__ == "__main__":
    backfill_history()
