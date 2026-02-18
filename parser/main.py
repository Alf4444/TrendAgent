import json
from pathlib import Path
from parser.pfa import parse_pfa_from_text

ROOT = Path(__file__).resolve().parents[1]
TEXT_DIR = ROOT / "build" / "text"
OUT_FILE = ROOT / "data" / "latest.json"
CONFIG_FILE = ROOT / "config" / "pfa_pdfs.json"

def main():
    if not CONFIG_FILE.exists():
        print("Config fil mangler!")
        return

    with open(CONFIG_FILE, "r") as f:
        isins = json.load(f)

    results = []
    print(f"Starter parsing af {len(isins)} fonde fra config.")

    for isin in isins:
        isin = isin.strip()
        txt_file = TEXT_DIR / f"{isin}.txt"
        
        if txt_file.exists():
            text = txt_file.read_text(encoding="utf-8", errors="ignore")
            data = parse_pfa_from_text(isin, text)
        else:
            data = {"pfa_id": isin, "nav": None, "nav_date": None, "currency": None}
            print(f"[ADVARSEL] Tekstfil mangler for {isin}")
        
        data["url"] = f"https://pfapension.os.fundconnect.com/api/v1/public/printer/solutions/default/factsheet?language=da-DK&isin={isin}"
        data["isin"] = isin
        
        results.append(data)
        print(f"[LOG] {isin}: Kurs={data['nav']}, Dato={data['nav_date']}")

    OUT_FILE.parent.mkdir(exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"Færdig! latest.json indeholder nu {len(results)} fonde.")

if __name__ == "__main__":
    main()
