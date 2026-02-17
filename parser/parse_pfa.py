# parser/parse_pfa.py
"""
TrendAgent - PDF download & parsing

Funktionalitet:
- Læser data/funds.csv (kolonner: isin,source_url)
- Downloader PDF pr. fond (requests; UA/Referer; retry/backoff)
- Ekstraherer tekst (pdfminer) fra BytesIO-stream
- Finder "Indre værdi" (NAV) og "Indre værdi dato" via robust heuristik:
    * 'Stamdata'-blok: etiketter i én kolonne, værdier efterfølgende linjer
    * Fallback: rullende vindue (op til +5 linjer) og flere nøgleord (NAV/Kurs)
- Skriver latest.json (run_date=YYYY-MM-DD, rows=[{isin, nav, nav_date, ...}])
- Gemmer parse-debug:
    build/pdfs/<isin>.pdf
    build/text/<isin>.txt
- Understøtter --mock (syntetiske værdier) som fallback/test

Kørsel lokalt (i repo-roden):
    python parser/parse_pfa.py --out latest.json
    python parser/parse_pfa.py --out latest.json --mock
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import time
from datetime import date, datetime
from typing import Optional, Tuple, Dict, Any, List

import requests
from pdfminer.high_level import extract_text  # korrekt import for pdfminer.six

UA = "TrendAgent/1.0 (+https://github.com/)"
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/pdf,*/*;q=0.8",
    "Referer": "https://www.pfa.dk/",
}

# ---------- utils ----------

def ensure_dir(path: str) -> None:
    """Sørg for at mappen til 'path' findes."""
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def load_funds(path: str = "data/funds.csv") -> List[Dict[str, str]]:
    funds: List[Dict[str, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            isin = (row.get("isin") or "").strip()
            url = (row.get("source_url") or "").strip()
            if isin and url:
                funds.append({"isin": isin, "source_url": url})
    return funds

def http_get(url: str, retries: int = 3, backoff: float = 1.5, timeout: int = 45) -> Dict[str, Any]:
    """
    Robust GET med få retrys. Returnerer dict:
    {'ok': bool, 'status': int, 'ct': str|None, 'content': bytes|None, 'err': str|None}
    """
    last_err: Optional[str] = None
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
    """
    Dansk formatering -> float:
      "1.234,56" -> 1234.56
      "129,15"   -> 129.15
    """
    if not s:
        return None
    t = s.strip().replace(" ", "")
    t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None

def parse_date_to_iso(s: str) -> Optional[str]:
    """
    Parse dd-mm-åååå / dd.mm.åååå / dd/mm/åååå -> ISO (YYYY-MM-DD).
    Fald tilbage til datetime.fromisoformat.
    """
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
                dt = datetime(int(y), int(m), int(d))
                return dt.date().isoformat()
            except Exception:
                pass
    try:
        return datetime.fromisoformat(t).date().isoformat()
    except Exception:
        return None

# ---------- parsing heuristics ----------

def extract_fields_from_text(text: str) -> Tuple[Optional[float], Optional[str]]:
    """
    FundConnect-venlig heuristik:
    1) Find et 'Stamdata'-lignende blok hvor etiketter (Opstart, Valuta, Type, Indre værdi, Indre værdi dato, …)
       står i én kolonne og værdier kommer efterfølgende i samme rækkefølge.
    2) Par etiketter med deres efterfølgende linjer (label->value).
    3) Ekstrahér:
       - NAV  = first_number_candidate(value_line) for "Indre værdi"/"NAV"/"Kurs"
       - DATO = first_date_candidate(value_line)  for "Indre værdi dato"
    4) Fallback: rullende vindue (op til +5 linjer) med brede nøgleord (nav/kurs mv.).
    """
    nav_val: Optional[float] = None
    nav_date_iso: Optional[str] = None

    # Hjælpere
    def clean_value_string(s: str) -> str:
        junk = [
            "DKK", "dkk", "Kr.", "kr.", "kr",
            "Kurs", "kurs",
            "Indre", "indre", "værdi", "værdi:", "værdi.", "værdi,",
            "pr.", "pr", "Dato", "dato:", "dato.", "dato,"
        ]
        out = s
        for j in junk:
            out = out.replace(j, " ")
        return out

    def first_number_candidate(s: str) -> Optional[float]:
        stage = (
            s.replace(":", " ")
             .replace("•", " ")
             .replace("|", " ")
             .replace("(", " ").replace(")", " ")
             .replace("%", " ")
        )
        tokens = stage.split()
        for tk in tokens:
            tk = tk.strip().strip(";,:.")
            val = normalize_decimal(tk)
            if val is not None:
                return val
        return None

    def first_date_candidate(s: str) -> Optional[str]:
        stage = s.replace("pr.", " ").replace("pr", " ")
        tokens = stage.split()
        # tjek både enkelt-token og simpel token-sammenkædning
        for i, tk in enumerate(tokens):
            iso = parse_date_to_iso(tk.strip(".:,;"))
            if iso:
                return iso
            if i + 1 < len(tokens):
                comb = (tk + tokens[i + 1]).strip(".:,;")
                iso = parse_date_to_iso(comb)
                if iso:
                    return iso
        return None

    lines: List[str] = [ln.strip() for ln in text.splitlines() if ln.strip()]
    n = len(lines)
    lower = [ln.lower() for ln in lines]

    # --- 1) Forsøg at finde 'Stamdata'-blok ---
    start_idx: Optional[int] = None
    for i, low in enumerate(lower):
        if "stamdata" in low:
            start_idx = i
            break
        # alternativ startdetektion: indenfor 6 linjer ses både 'indre værdi' og 'indre værdi dato'
        window = " ".join(lower[i:i + 6])
        if ("indre værdi" in window or "indrevaerdi" in window or "indreværdi" in window or "nav" in window or "kurs" in window) and \
           ("indre værdi dato" in window or "indre vaerdi dato" in window or "indreværdi dato" in window):
            start_idx = i
            break

    end_idx: Optional[int] = None
    if start_idx is not None:
        for j in range(start_idx + 1, n):
            low = lower[j]
            # heuristik for slut på blok (andre sektioner/overskrifter)
