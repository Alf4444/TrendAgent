import pdfplumber
import os
from pathlib import Path

def convert_pdfs():
    base_dir = Path(__file__).resolve().parents[1]
    pdf_dir = base_dir / "build" / "pdf"
    txt_dir = base_dir / "build" / "text"
    txt_dir.mkdir(parents=True, exist_ok=True)

    for pdf_path in pdf_dir.glob("*.pdf"):
        txt_path = txt_dir / f"{pdf_path.stem}.txt"
        print(f"Konverterer: {pdf_path.name}")
        
        full_text = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    # Udtrækker tekst fra både brødtekst og tabeller
                    text = page.extract_text()
                    if text:
                        full_text.append(text)
            
            txt_path.write_text("\n".join(full_text), encoding="utf-8")
        except Exception as e:
            print(f"Fejl ved {pdf_path.name}: {e}")

if __name__ == "__main__":
    convert_pdfs()
