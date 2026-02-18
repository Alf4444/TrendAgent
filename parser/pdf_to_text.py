import pdfplumber
import os
from pathlib import Path

def convert_pdfs():
    base_dir = Path(__file__).resolve().parents[1]
    pdf_dir = base_dir / "build" / "pdf"
    txt_dir = base_dir / "build" / "text"
    txt_dir.mkdir(parents=True, exist_ok=True)

    pdf_files = list(pdf_dir.glob("*.pdf"))
    if not pdf_files:
        print("Ingen PDF-filer fundet i build/pdf/")
        return

    for pdf_path in pdf_files:
        txt_path = txt_dir / f"{pdf_path.stem}.txt"
        print(f"Læser PDF: {pdf_path.name}")
        
        full_text = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    # extract_text() fanger nu også data fra tabellerne korrekt
                    text = page.extract_text()
                    if text:
                        full_text.append(text)
            
            txt_path.write_text("\n".join(full_text), encoding="utf-8")
        except Exception as e:
            print(f"Fejl ved konvertering af {pdf_path.name}: {e}")

if __name__ == "__main__":
    convert_pdfs()
