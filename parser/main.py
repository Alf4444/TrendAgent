# parser/main.py
import json
import re
from pathlib import Path
from parser.pfa import parse_pfa_from_text

ROOT = Path(__file__).resolve().parents[1]
TEXT_DIR = ROOT / "build" / "text"
OUT_FILE = ROOT / "data" / "latest.json"
CONFIG_PDFS = ROOT / "config" / "pfa_pdfs.json"

def main():
    print("[PARSE] Starter parsing...")
    
    # Indlæs links fra config/pfa_pdfs.json
    links = {}
    if CONFIG_PDFS.exists():
        links = json.loads(CONFIG_PDFS.read_text(encoding="utf-8"))

    results = []
    
    for txt_file in TEXT_DIR.glob("*.txt"):
        pfa_id = txt_file.stem
        text = txt_file.read_text(encoding="utf-8", errors="ignore")
        
        # 1. Kør den robuste parser (pfa.py)
        data = parse_pfa_from_text(pfa_id, text)
        
        # 2. Hent PDF URL og find ISIN i den (hvis muligt)
        pdf_url = links.get(pfa_id, "")
        isin_match = re.search(r"isin=([A-Z0-9]+)", pdf_url)
        isin = isin_match.group(1) if isin_match else pfa_id
        
        # 3. Berig data
        data.update({
            "isin": isin,
            "pfa_id": pfa_id,
            "url": pdf_url,
            "name": pfa_id # Navnet kommer ofte øverst i TXT, men PFA-ID er unikt
        })
        
        results.append(data)
        print(f"[OK] {pfa_id} -> NAV: {data['nav']}, Dato: {data['nav_date']}")

    # Gem til data/latest.json
    OUT_FILE.parent.mkdir(exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"[DONE] Gemte {len(results)} fonde i {OUT_FILE}")

if __name__ == "__main__":
    main()
