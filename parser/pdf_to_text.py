# parser/pdf_to_text.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Dict, Optional

import requests
from pdfminer.high_level import extract_text

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config" / "pfa_pdfs.json"

PDF_DIR = ROOT / "build" / "pdf"
TXT_DIR = ROOT / "build" / "text"
TIMEOUT = 30  # sekunder for download


def ensure_dirs() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    TXT_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> Dict[str, str]:
    """
    Læs ISIN -> PDF URL mapping fra config/pfa_pdfs.json.
    Hvis filen ikke findes, returneres tom mapping (kun lokal PDF->TXT konvertering køres).
    """
    if not CONFIG.exists():
        print(f"[PDF2TXT] No config file found at {CONFIG} — skipping downloads.")
        return {}
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            print(f"[PDF2TXT] Invalid JSON structure in {CONFIG} (expected object).")
            return {}
        return {str(k): str(v) for k, v in data.items()}
    except Exception as e:
        print(f"[PDF2TXT] Failed to load {CONFIG}: {e}")
        return {}


def download_pdf(isin: str, url: str) -> Optional[Path]:
    """
    Downloader en PDF til build/pdf/<ISIN>.pdf hvis URL er sat.
    Returnerer sti til PDF eller None ved fejl.
    """
    try:
        print(f"[PDF2TXT] Downloading {isin} from {url}")
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
    Konverter PDF -> TXT ved hjælp af pdfminer.six
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

    # 1) Download PDF’er fra config (hvis config findes og URLs er sat)
    mapping = load_config()
    for isin, url in sorted(mapping.items()):
        if url.strip():
            download_pdf(isin, url.strip())

    # 2) Konverter alle PDF’er i build/pdf → build/text
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print("[PDF2TXT] No PDFs found in build/pdf — nothing to convert.")
    count_ok = 0
    for pdf in pdfs:
        if pdf_to_text(pdf):
            count_ok += 1

    print(f"[PDF2TXT] Done. PDFs: {len(pdfs)}  TXT written: {count_ok}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
