# parser/parse_pfa.py
"""
Fase 2: Download og parse PFA fakta-PDF'er for at udtrække:
- "Indre værdi" (NAV) som decimaltal
- "Indre værdi dato" (YYYY-MM-DD)

Design:
- Læs data/funds.csv (kolonner: isin, source_url)
- For hver fond:
  - download PDF (requests, user-agent, retry)
  - extract_text (pdfminer.high_level)
  - defensiv substring/split: find linjer med "Indre værdi" og "Indre værdi dato"
  - konverter værdier (komma->punktum, strip)
- Returnér 'latest.json' som:
  { "rows": [ {isin, nav, nav_date}, ... ], "run_date": "YYYY-MM-DD" }

Robusthed:
- Per-fond try/except -> fortsæt hvis én PDF fejler
- Tolerer tusindtalsseparatorer og komma-decimaler
- Dato genkendes via enkle mønstre (dd-mm-åååå eller dd.mm.åååå); normaliser til ISO
- Hvis felt mangler -> skriv None (og tag den i rapportsøjlen som '-')

Kørsel:
python parser/parse_pfa.py --out latest.json
python parser/parse_pfa.py --out latest.json --mock   # fallback
"""

import argparse
import csv
import json
import os
import time
from datetime import date, datetime
from typing import Optional, Tuple

import requests
from pdfminer.high_level import extract_text

UA = "TrendAgent/1.0 (+https://github.com/)"

def load_funds(path="data/funds.csv"):
    funds = []
    with open(path, newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            isin = (row.get("isin") or "").strip()
            url = (row.get("source_url") or "").strip()
            if isin and url:
                funds.append({"isin": isin, "source_url": url})
    return funds

def http_get(url: str, retries: int = 3, backoff: float = 1.5, timeout: int = 30) -> Optional[bytes]:
    last_exc = None
    headers = {"User-Agent": UA}
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            # accepter 200-OK og PDF content-type (ikke et hårdt krav, nogle servere sætter ikke korrekt type)
            if resp.status_code == 200 and resp.content:
                return resp.content
            else:
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
        except Exception as e:
            last_exc = e
        time.sleep(backoff ** attempt)  # eksponentiel backoff
    print(f"[WARN] GET failed for {url}: {last_exc}")
    return None

def normalize_decimal(s: str) -> Optional[float]:
    if not s:
        return None
    # Fjern mellemrum, tusindtalssep . eller space, og brug . som decimal
    t = s.strip().replace(" ", "")
    # Typisk dansk format: "1.234,56" -> "1234.56"
    t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None

def parse_date_to_iso(s: str) -> Optional[str]:
    if not s:
        return None
    t = s.strip()
    # Tillad varianter: 16-02-2026, 16.02.2026, 16/02/2026
    for sep in ("-", ".", "/"):
        parts = t.split(sep)
        if len(parts) == 3 and all(parts):
            d, m, y = parts
            # håndter 2-cifret år evt.
            if len(y) == 2:
                y = "20" + y
            try:
                dt = datetime(int(y), int(m), int(d))
                return dt.date().isoformat()
            except Exception:
                pass
    # Fallback: hvis allerede ISO
    try:
        return datetime.fromisoformat(t).date().isoformat()
    except Exception:
        return None

def extract_fields_from_text(text: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Heuristik:
    - Find linjer der indeholder 'Indre værdi' -> tal efter kolon
    - Find linjer der indeholder 'Indre værdi dato' -> dato efter kolon
    """
    nav_val: Optional[float] = None
    nav_date_iso: Optional[str] = None

    # Split pr. linje og trim
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        low = ln.lower()
        # NAV
        if ("indre værdi" in low or "indrevaerdi" in low or "indreværd" in low):
            # Eksempler:
            # "Indre værdi: 145,23"
            # "Indre værdi 145,23 DKK"
            after = ln
            if ":" in ln:
                after = ln.split(":", 1)[1]
            # tag første token der ligner tal
            tokens = after.replace("DKK", "").replace("kr", "").split()
            for tk in tokens:
                val = normalize_decimal(tk)
                if val is not None:
                    nav_val = val
                    break

        # NAV dato
        if ("indre værdi dato" in low) or ("indreværdi dato" in low) or ("indre vaerdi dato" in low):
            # "Indre værdi dato: 16-02-2026"
            after = ln.split(":", 1)[1].strip() if ":" in ln else ln
            iso = parse_date_to_iso(after)
            if iso:
                nav_date_iso = iso

        # Early exit hvis begge er fundet
        if nav_val is not None and nav_date_iso is not None:
            break

    return nav_val, nav_date_iso

def parse_pdf_bytes(pdf_bytes: bytes) -> Tuple[Optional[float], Optional[str]]:
    # Ekstraher brødtekst. pdfminer kan returnere lang tekst; vi kører bare heuristikken på hele.
    text = extract_text(pdf_bytes)
    return extract_fields_from_text(text)

def build_latest(funds):
    rows = []
    for f in funds:
        isin = f["isin"]
        url = f["source_url"]
        nav = None
        nav_date = None
        try:
            content = http_get(url)
            if content:
                nav, nav_date = parse_pdf_bytes(content)
            else:
                print(f"[WARN] No content for {isin}")
        except Exception as e:
            print(f"[WARN] Parse failed for {isin}: {e}")

        rows.append({
            "isin": isin,
            "nav": nav,
            "nav_date": nav_date,
            # felter til daglig/ugentlig skabelon; kan udfyldes af model senere
            "change_pct": None,
            "trend_shift": False,
            "cross_20_50": False,
            "trend_state": "NEUTRAL",
            "week_change_pct": None,
            "ytd_return": None,
            "drawdown": None,
        })
    return rows

def build_mock_latest(funds):
    # fallback hvis --mock
    base_nav = 100.0
    res = []
    for i, f in enumerate(funds):
        nav = base_nav + i * 0.37
        res.append({
            "isin": f["isin"],
            "nav": round(nav, 2),
            "nav_date": date.today().isoformat(),
            "change_pct": 0.0,
            "trend_shift": False,
            "cross_20_50": False,
            "trend_state": "NEUTRAL",
            "week_change_pct": 0.0,
            "ytd_return": 0.0,
            "drawdown": 0.0,
        })
    return res

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="latest.json")
    ap.add_argument("--mock", action="store_true")
    args = ap.parse_args()

    funds = load_funds()
    if args.mock:
        rows = build_mock_latest(funds)
    else:
        rows = build_latest(funds)

    payload = {"rows": rows, "run_date": date.today().isoformat()}
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Wrote {args.out} with {len(rows)} rows")

if __name__ == "__main__":
    main()
