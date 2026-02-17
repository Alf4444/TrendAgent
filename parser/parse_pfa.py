# parser/parse_pfa.py
"""
TrendAgent - PDF download & parsing

- Læser data/funds.csv (isin,source_url)
- Downloader PDF (requests m. UA/Referer; retry/backoff)
- Ekstraherer tekst (pdfminer) fra BytesIO-stream
- Finder "Indre værdi" (NAV) og "Indre værdi dato" via robust Stamdata-heuristik:
  * Lås på 'Stamdata'
  * Find etiketter: Opstart, Valuta, Type, Indre værdi, Indre værdi dato, Bæredygtighed
  * Læs præcis samme antal værdilinjer efter 'Bæredygtighed' og map i rækkefølge
- Logger kort parse-resultat pr. ISIN
- Gemmer parse-debug (PDF + tekstuddrag)
- Understøtter --mock
"""

import argparse
import csv
import io
import json
import os
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import requests
from pdfminer.high_level import extract_text

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
    """Returner dict: {'ok': bool, 'status': int, 'ct': str|None, 'content': bytes|None, 'err': str|None}"""
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
    """Dansk formatering -> float. '1.234,56' -> 1234.56"""
    if not s:
        return None
    t = s.strip().replace(" ", "")
    t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None

def parse_date_to_iso(s: str) -> Optional[str]:
    """dd-mm-åååå / dd.mm.åååå / dd/mm/åååå -> YYYY-MM-DD"""
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
    1) Find 'Stamdata'-blok og par 6 etiketter -> 6 værdier.
    2) Fallback: rullende vindue (op til +12 linjer).
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
        for tk in stage.split():
            tk = tk.strip().strip(";,:.")
            val = normalize_decimal(tk)
            if val is not None:
                return val
        return None

    def first_date_candidate(s: str) -> Optional[str]:
        stage = s.replace("pr.", " ").replace("pr", " ")
        tokens = stage.split()
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
    lower = [ln.lower() for ln in lines]
    n = len(lines)

    # --- 1) Find 'Stamdata'-område ---
    start_idx: Optional[int] = None
    for i, low in enumerate(lower):
        if "stamdata" in low:
            start_idx = i
            break
        window = " ".join(lower[i:i + 8])
        if ("indre værdi" in window or "indrevaerdi" in window or "indreværdi" in window or "nav" in window or "kurs" in window) and \
           ("indre værdi dato" in window or "indre vaerdi dato" in window or "indreværdi dato" in window):
            start_idx = i
            break

    end_idx: Optional[int] = None
    if start_idx is not None:
        for j in range(start_idx + 1, n):
            low = lower[j]
            if low in ("afkast", "omkostninger", "risiko", "risikoklasse", "afdeling"):
                end_idx = j
                break
        if end_idx is None:
            end_idx = min(n, start_idx + 80)

    # --- 2) Parring label->værdi (strengt 6 etiketter i rækkefølge) ---
    if start_idx is not None and end_idx is not None and end_idx > start_idx + 1:
        block = lines[start_idx:end_idx]
        block_low = [b.lower() for b in block]

        required = ["opstart", "valuta", "type", "indre værdi", "indre værdi dato", "bæredygtighed"]

        # Find første forekomst af hver required label i rækkefølge (efter hinanden i blokken)
        pos: Dict[str, int] = {}
        cur = 0
        for req in required:
            found = False
            for idx in range(cur, len(block_low)):
                if req in block_low[idx] or (req == "bæredygtighed" and "baeredygtighed" in block_low[idx]):
                    pos[req] = idx
                    cur = idx + 1
                    found = True
                    break
