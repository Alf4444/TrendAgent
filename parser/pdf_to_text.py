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
CFG_URLMAP = CFG_DIR / "pfa_pdfs.json"   # {"PFA000002738": "https://...factsheet?...&isin=PFA000002738", ...}

PDF_DIR = ROOT / "build" / "pdf"
TXT_DIR = ROOT / "build" / "text"
TIMEOUT = 40  # sekunder

HEADERS = {
    "User-Agent": "TrendAgent/1.0 (+https://github.com/your-org/your-repo)"
}

def default_fundconnect_url(isin: str, language: str = "da-DK") -> str:
    # FundConnect-faktaark pr. ISIN (stabil struktur)
    return (
        "https://pfapension.os.fundconnect.com/"
        "api/v1/public/printer/solutions/default/factsheet"
        f"?isin={isin}&language={language}"
    )

def ensure_dirs() -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    TXT_DIR.mkdir(parents=True, exist_ok=True)

def load_isins() -> Set[str]:
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
    if not CFG_URLMAP.exists():
        return {}
    try:
        data = json.loads(CFG_URLMAP.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            print(f"[PDF2TXT] Invalid JSON in {CFG_URLMAP} (expected object).")
            return {}
        return {str(k).strip(): str(v).strip() for k, v in data.items() if str(v).strip()}
    except Exception as e:
        print(f"[PDF2TXT] Failed to load {CFG_URLMAP}: {e}")
        return {}

def pick_url_for_isin(isin: str, overrides: Dict[str, str]) -> str:
    return overrides.get(isin) or default_fundconnect_url(isin)

def download_pdf(isin: str, url: str) -> Optional[Path]:
    try:
        print(f"[PDF2TXT] Downloading {isin} → {url}")
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        out = PDF_DIR / f"{isin}.pdf"
        out.write_bytes(r.content)
        print(f"[PDF2TXT] Wrote {out} ({len(r.content)} bytes)")
        return out
    except Exception as e:
        print(f"[PDF2TXT] Download failed for {isin}: {e}")
        return None

def pdf_to_text(pdf_path: Path) -> Optional[Path]:
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
    isins = load_isins()
    overrides = load_url_overrides()

    if not isins:
        for p in sorted(PDF_DIR.glob("*.pdf")):
            isins.add(p.stem.strip())
        if not isins:
            # Fallback (kan fjernes når config er i brug)
            isins.update({"PFA000002738", "PFA000002735", "PFA000002761"})
            print("[PDF2TXT] No ISINs in config; using default 3 for now.")

    downloaded = []
    for isin in sorted(isins):
        url = pick_url_for_isin(isin, overrides)
        pdf_path = download_pdf(isin, url)
        if pdf_path:
            downloaded.append(pdf_path)

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
