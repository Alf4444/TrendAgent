import json
import os
from pathlib import Path
from parser.pfa import parse_pfa_from_text

ROOT = Path(__file__).resolve().parents[1]
TEXT_DIR = ROOT / "build/text"
OUT_FILE = ROOT / "data/latest.json"
HISTORY_FILE = ROOT / "data/history.json"
CONFIG_FILE = ROOT / "config/pfa_pdfs.json"

def main():
    if not CONFIG_FILE.exists(): return

    with open(CONFIG_FILE, "r") as f:
        isins = json.load(f)

    # Spring over fonde der starter med # eller -
    active_isins = [i.strip() for i in isins if not i.strip().startswith(("#", "-"))]
    results = []
    
    history = {}
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r") as f:
                history = json.load(f)
        except: history = {}

    for isin in active_isins:
        txt_file = TEXT_DIR / f"{isin}.txt"
        
        # Opret basis data for at undgå KeyError
        data = {
            "isin": isin,
            "url": f"https://pfapension.os.fundconnect.com/api/v1/public/printer/solutions/default/factsheet?language=da-DK&isin={isin}",
            "name": "Mangler data",
            "nav": None,
            "nav_date": None
        }
        
        if txt_file.exists():
            text = txt_file.read_text(encoding="utf-8", errors="ignore")
            parsed = parse_pfa_from_text(isin, text)
            data.update(parsed) # Opdater med rigtige tal fra PDF
            
            # Gem i historikken
            if data["nav"] and data["nav_date"]:
                if isin not in history: history[isin] = {}
                history[isin][data["nav_date"]] = data["nav"]
        
        results.append(data)

    OUT_FILE.parent.mkdir(exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
        
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

    print(f"Parsing færdig for {len(results)} aktive fonde.")

if __name__ == "__main__":
    main()
