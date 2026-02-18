import json
from pathlib import Path
from parser.pfa import parse_pfa_from_text

ROOT = Path(__file__).resolve().parents[1]
TEXT_DIR = ROOT / "build" / "text"
OUT_FILE = ROOT / "data" / "latest.json"

def main():
    results = []
    txt_files = list(TEXT_DIR.glob("*.txt"))
    print(f"Starter parsing af {len(txt_files)} filer.")

    for txt_file in txt_files:
        pfa_id = txt_file.stem
        text = txt_file.read_text(encoding="utf-8", errors="ignore")
        
        data = parse_pfa_from_text(pfa_id, text)
        data["url"] = f"https://pfapension.os.fundconnect.com/api/v1/public/printer/solutions/default/factsheet?language=da-DK&isin={pfa_id}"
        data["isin"] = pfa_id
        
        results.append(data)
        print(f"[LOG] {pfa_id} færdig: Kurs={data['nav']}, Dato={data['nav_date']}")

    OUT_FILE.parent.mkdir(exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("Parsing fuldført. latest.json er opdateret.")

if __name__ == "__main__":
    main()
