import json
import random
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEST_FILE = ROOT / "data/latest.json"
HISTORY_FILE = ROOT / "data/history.json"

def generate_test_history():
    if not LATEST_FILE.exists():
        print("Fejl: latest.json mangler. Kør din main robot først.")
        return

    with open(LATEST_FILE, "r", encoding="utf-8") as f:
        latest_data = json.load(f)

    history = {}
    today = datetime.now()

    for item in latest_data:
        isin = item['isin']
        current_nav = item.get('nav', 100.0)
        history[isin] = {}
        
        temp_nav = current_nav
        # Generer 250 dages historik
        for i in range(250, -1, -1):
            date_str = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            # Skaber lidt tilfældig svingning (-1% til +1% per dag)
            change = 1 + (random.uniform(-0.01, 0.011)) 
            temp_nav *= change
            history[isin][date_str] = round(temp_nav, 2)

    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)
    
    print(f"Succes! Genereret 250 dages historik for {len(latest_data)} fonde.")

if __name__ == "__main__":
    generate_test_history()
