# parser/pdf_to_text.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Dict, Optional, Set

import requests
from pdfminer.high_level import extract_text

ROOT = Path(__file__).resolve().parents[1]
CFG_DIR = ROOT / "config"
CFG_DIR.mkdir(parents=True, exist_ok=True)

CFG_ISINS = CFG_DIR / "pfa_isins.json"   # {"isins": ["PFA000002738", ...]}
CFG_URLMAP = CFG_DIR / "pfa_pdfs.json"   # {"PFA000002738": "https://.../738.pdf", ...}

PDF_DIR = ROOT / "build" / "pdf"
TXT_DIR = ROOT / "build" / "text"
TIMEOUT = 40  # sekunder for download

# Standard FundConnect endpoint (danner URL ud fra ISIN)
# Kilde/dokumentation: fundconnect endpoint med ISIN-parametre ─ se citations i svaret.
def default_fundconnect_url(isin: str, language: str = "da-DK") -> str:
    return (
        "https://pfapension.os.fundconnect.com/"
        "api/v1/public/printer/solutions/default/factsheet"
        f"?isin={isin}&language={language}"
    )

def ensure_dirs() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    TXT_DIR.mkdir(parents=True, exist_ok=True)

def load_isins() -> Set[str]:
    """
    Læs ISINs fra config/pfa_isins.json (optional).
    Returnerer et sæt (kan være tomt).
    Strukturen forventes: {"isins": ["PFA000002738", ...]}.
    """
    if not CFG_ISINS.exists():
        return set()
    try:
        data = json.loads(CFG_ISINS.read_text(encoding="utf-8"))
        arr = data.get("isins", []) if isinstance(data, dict) else []
        return {str(x).strip() for x in arr if str(x).strip()}
    except Exception as e:
        print(f"[PDF2TXT] Failed to load {CFG_ISINS}: {e}")
        return set()

def load_url_overrides() -> Dict[str, str]:
    """
    Læs valgfrie overrides fra config/pfa_pdfs.json.
    Struktur: {"ISIN": "https://...pdf", ...}
    """
    if not CFG_URLMAP.exists():
        return {}
    try:
        data = json.loads(CFG_URLMAP.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            print(f"[PDF2TXT] Invalid JSON in {CFG_URLMAP} (expected object).")
            return {}
        # Rens tomme værdier væk
        return {str(k).strip(): str(v).strip() for k, v in data.items() if str(v).strip()}
    except Exception as e:
        print(f"[PDF2TXT] Failed to load {CFG_URLMAP}: {e}")
        return {}

def pick_url_for_isin(isin: str, overrides: Dict[str, str]) -> str:
    """
    Vælg URL til download:
      1) Brug override hvis sat i config
      2) Ellers generér FundConnect-standard ud fra ISIN
    """
    return overrides.get(isin) or default_fundconnect_url(isin)

def download_pdf(isin: str, url: str) -> Optional[Path]:
    """
    Download PDF til build/pdf/<ISIN>.pdf
    """
    try:
        print(f"[PDF2TXT] Downloading {isin} → {url}")
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        out = PDF_DIR / f"{isin}.pdf"
        out.write_bytes(r.content)
        print(f"[PDF2TXT] Wrote {out} ({len(r.content)} bytes)")
        return out
    except Exception as e:
        print(f"[PDF2TXT] Download failed for {isin}: {e}")
        return None

def pdf_to_text(pdf_path: Path) -> Optional[Path]:
    """
    Konverter PDF -> TXT (utf-8) i build/text/<ISIN>.txt
    """
    try:
        txt = extract_text(str(pdf_path)) or ""
        out = TXT_DIR / (pdf_path.stem + ".txt")
        out.write_text(txt, encoding="utf-8")
        print(f"[PDF2TXT] Extracted → {out} ({len(txt)} chars)")
        return out
    except Exception as e:
        print(f"[PDF2TXT] Extraction failed for {pdf_path.name}: {e}")
        return None

def main() -> None:
    ensure_dirs()

    # 1) Saml mål-ISINs
    isins = load_isins()
    overrides = load_url_overrides()

    # Hvis ingen ISINs i config, forsøg at gætte fra allerede liggende PDF-navne
    if not isins:
        for p in sorted(PDF_DIR.glob("*.pdf")):
            isins.add(p.stem.strip())
        if not isins:
            # fallback til de 3 du havde i seed – kan udvides når du vil
            isins.update({"PFA000002738", "PFA000002735", "PFA000002761"})
            print("[PDF2TXT] No ISINs in config; using default 3 for now.")

    # 2) Download alle PDF’er (overrides eller default FundConnect-URL)
    downloaded = []
    for isin in sorted(isins):
        url = pick_url_for_isin(isin, overrides)
        pdf_path = download_pdf(isin, url)
        if pdf_path:
            downloaded.append(pdf_path)

    # 3) Konverter ALLE PDF’er der ligger i build/pdf (inkl. dem som måske lå i forvejen)
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print("[PDF2TXT] No PDFs found in build/pdf — nothing to convert.")
    ok = 0
    for pdf in pdfs:
        if pdf_to_text(pdf):
            ok += 1

    print(f"[PDF2TXT] Done. ISINs target: {len(isins)}  PDFs seen: {len(pdfs)}  TXT written: {ok}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
