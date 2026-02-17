# parser/parse_pfa.py
"""
TrendAgent - PDF download & parsing
- Læser data/funds.csv (isin,source_url)
- Downloader PDF (requests m. UA/Referer)
- Ekstraherer tekst (pdfminer) fra BytesIO-stream
- Finder "Indre værdi" og "Indre værdi dato" med defensiv heuristik
- Gemmer parse-debug (build/pdfs/*.pdf, build/text/*.txt)
- Skriver latest.json
- Understøtter --mock som fallback
"""

import argparse
import csv
import io
import json
import os
import time
from datetime import date, datetime
from typing import Optional, Tuple, Dict, Any

import requests
from pdfminer.high_level import extract_text  # korrekt import

UA = "TrendAgent/1.0 (+https://github.com/)"
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/pdf,*/*;q=0.8",
    "Referer": "https://www.pfa.dk/",
}

# ---------- utils ----------

def ensure_dir(path: str):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def load_funds(path="data/funds.csv"):
    funds = []
    with open(path, newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            isin = (row.get("isin") or "").strip()
            url  = (row.get("source_url") or "").strip()
            if isin and url:
                funds.append({"isin": isin, "source_url": url})
    return funds

def http_get(url: str, retries: int = 3, backoff: float = 1.5, timeout: int = 45) -> Dict[str, Any]:
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
            ct = resp.headers.get("Content-Type", "")
            if resp.status_code == 200 and resp.content:
                return {"ok": True, "status": resp.status_code, "ct": ct, "content": resp.content, "err": None}
            last_err = f"HTTP {resp.status_code} (ct={ct})"
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(backoff ** attempt)
    return {"ok": False, "status": 0, "ct": None, "content": None, "err": last_err}

def normalize_decimal(s: str) -> Optional[float]:
    if not s:
        return None
    t = s.strip().replace(" ", "")
    t = t.replace(".", "").replace(",", ".")  # "1.234,56" -> "1234.56"
    try:
        return float(t)
    except ValueError:
        return None

def parse_date_to_iso(s: str) -> Optional[str]:
    if not s:
        return None
    t = s.strip()
    for sep in ("-", ".", "/"):
        parts = t.split(sep)
        if len(parts) == 3 and all(parts):
            d, m, y = parts
            if len(y) == 2:
                y = "20" + y
            try:
                return datetime(int(y), int(m), int(d)).date().isoformat()
            except Exception:
                pass
    try:
        return datetime.fromisoformat(t).date().isoformat()
    except Exception:
        return None

# ---------- parsing heuristics ----------

def extract_fields_from_text(text: str) -> Tuple[Optional[float], Optional[str]]:
    """Fang NAV/dato; kig også på næste linje hvis værdien ikke står efter kolon."""
    nav_val: Optional[float] = None
    nav_date_iso: Optional[str] = None

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    want_nav_next = False
    want_date_next = False

    for ln in lines:
        low = ln.lower()

        if want_nav_next and nav_val is None:
            cand = normalize_decimal(ln)
            if cand is not None:
                nav_val = cand
            want_nav_next = False

        if want_date_next and nav_date_iso is None:
            iso = parse_date_to_iso(ln)
            if iso:
                nav_date_iso = iso
            want_date_next = False

        if ("indre værdi" in low) or ("indrevaerdi" in low) or ("indreværdi" in low):
            after = ln.split(":", 1)[1] if ":" in ln else ln
            for j in ["DKK", "kr", "Kurs", "kurs", "Indre", "indre", "værdi", "værdi:", "værdi.", "værdi,"]:
                after = after.replace(j, "")
            tokens = after.replace(",", " , ").replace(".", " . ").split()
            found = False
            for tk in tokens:
                val = normalize_decimal(tk)
                if val is not None:
                    nav_val = val
                    found = True
                    break
            if not found:
