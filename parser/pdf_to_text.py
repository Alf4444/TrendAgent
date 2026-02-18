import pdfplumber
import requests
import json
import os
from pathlib import Path

def download_and_convert():
    base_dir = Path(__file__).resolve().parents[1]
    pdf_dir = base_dir / "build" / "pdf"
    txt_dir = base_dir / "build" / "text"
    config_file = base_dir / "config" / "pfa_pdfs.json"
    
    pdf_dir.mkdir(parents=True, exist_ok=True)
    txt_dir.mkdir(parents=True, exist_ok=True)

    # Liste over dine PFA ISINs
    isins = [
        "PFA000002761", "PFA000002756", "PFA000002726", "PFA000002742",
        "PFA000002735", "PFA000002746", "PFA000002759", "PFA000002703",
        "PFA000002738", "PFA000002732", "PFA000002755"
    ]

    for isin in isins:
        pdf_path = pdf_dir / f"{isin.strip()}.pdf"
        txt_path = txt_dir / f"{isin.strip()}.txt"
        url = f"https://pfapension.os.fundconnect.com/api/v1/public/printer/solutions/default/factsheet?language=da-DK&isin={isin.strip()}"
        
        print(f"Henter PDF for {isin}...")
        try:
            r = requests.get(url, timeout=30)
            if r.status_code == 200:
                pdf_path.write_bytes(r.content)
                
                # Konverter med det samme til tekst
                with pdfplumber.open(pdf_path) as pdf:
                    text = ""
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
                    txt_path.write_text(text, encoding="utf-8")
                print(f"Færdig med {isin}")
            else:
                print(f"Fejl: Kunne ikke hente {isin} (Status: {r.status_code})")
        except Exception as e:
            print(f"Fejl ved {isin}: {e}")

if __name__ == "__main__":
    download_and_convert()
