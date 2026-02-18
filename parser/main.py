# parser/main.py
import json
from pathlib import Path
from parser.pfa import parse_pfa_from_text

ROOT = Path(__file__).resolve().parents[1]
TEXT_DIR = ROOT / "build" / "text"
OUT_FILE = ROOT / "data" / "latest.json"
CONFIG_PDFS = ROOT / "config" / "pfa_pdfs.json"

def main():
    print("[PARSE] Starter parsing af fonde...")
    
    # 1. Indlæs mapping (ISIN, Navne, URL'er) fra din nye config-fil
    mapping = {}
    if CONFIG_PDFS.exists():
        with open(CONFIG_PDFS, encoding="utf-8") as f:
            # Vi antager her at filen er en liste af objekter med "pfa_id", "isin", "name"
            # Hvis din struktur er anderledes, skal vi lige tilpasse denne linje
            data = json.load(f)
            # Vi laver et opslagsværk så vi hurtigt kan finde info via PFA-koden
            mapping = {item["pfa_id"]: item for item in data}

    results = []
    
    # 2. Gennemgå alle tekstfiler fra PDF-konverteringen
    for txt_file in TEXT_DIR.glob("*.txt"):
        pfa_id = txt_file.stem
        text = txt_file.read_text(encoding="utf-8")
        
        # Brug den nye robuste parser fra pfa.py
        data = parse_pfa_from_text(pfa_id, text)
        
        # Tilføj ekstra info fra din pfa_pdfs.json hvis den findes
        info = mapping.get(pfa_id, {})
        data["isin"] = info.get("isin", pfa_id)
        data["name"] = info.get("name", "Ukendt fond")
        data["url"] = info.get("url", "")
        
        results.append(data)
        print(f"[OK] Behandlede {pfa_id}: NAV={data['nav']}, Dato={data['nav_date']}")

    # 3. GEM DATA (Dette er det vigtige skridt!)
    OUT_FILE.parent.mkdir(exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"[DONE] Gemte {len(results)} fonde i {OUT_FILE}")

if __name__ == "__main__":
    main()
