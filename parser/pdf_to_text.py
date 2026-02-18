import pdfplumber
import requests
import json
from pathlib import Path

def download_and_convert():
    base_dir = Path(__file__).resolve().parents[1]
    pdf_dir = base_dir / "build" / "pdf"
    txt_dir = base_dir / "build" / "text"
    config_file = base_dir / "config" / "pfa_pdfs.json"
    
    pdf_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)

    if not config_file.exists():
        print(f"FEJL: Fandt ikke {config_file}")
        return
    
    with open(config_file, "r") as f:
        isins = json.load(f)

    print(f"Starter behandling af {len(isins)} fonde...")

    for isin in isins:
        isin = isin.strip()
        pdf_path = pdf_dir / f"{isin}.pdf"
        txt_path = txt_dir / f"{isin}.txt"
        url = f"https://pfapension.os.fundconnect.com/api/v1/public/printer/solutions/default/factsheet?language=da-DK&isin={isin}"
        
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                pdf_path.write_bytes(r.content)
                with pdfplumber.open(pdf_path) as pdf:
                    text = ""
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                    txt_path.write_text(text, encoding="utf-8")
                print(f"[OK] Downloadet og konverteret: {isin}")
            else:
                print(f"[FEJL] Kunne ikke hente {isin} (Status: {r.status_code})")
        except Exception as e:
            print(f"[FEJL] Problem med {isin}: {e}")

if __name__ == "__main__":
    download_and_convert()
