# parser/main.py
import json
from pathlib import Path
from parser.pfa import parse_pfa_from_text

ROOT = Path(__file__).resolve().parents[1]
TEXT_DIR = ROOT / "build" / "text"
OUT_FILE = ROOT / "data" / "latest.json"
CONFIG_PDFS = ROOT / "config" / "pfa_pdfs.json"

def main():
    links = {}
    if CONFIG_PDFS.exists():
        links = json.loads(CONFIG_PDFS.read_text(encoding="utf-8"))

    results = []
    
    for txt_file in TEXT_DIR.glob("*.txt"):
        pfa_id = txt_file.stem
        text = txt_file.read_text(encoding="utf-8", errors="ignore")
        
        # Kør selve parseren
        data = parse_pfa_from_text(pfa_id, text)
        
        # Tilføj URL fra config, hvis den findes
        data["url"] = links.get(pfa_id, "")
        if not data.get("isin"):
             data["isin"] = pfa_id # Fallback hvis ISIN mangler

        results.append(data)
        print(f"[OK] Parsede {pfa_id}: NAV={data['nav']}, Dato={data['nav_date']}")

    # Gem alt til latest.json
    OUT_FILE.parent.mkdir(exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

if __name__ == "__main__":
    main()
