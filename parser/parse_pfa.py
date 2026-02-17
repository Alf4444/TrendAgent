# parser/parse_pfa.py
"""
TrendAgent - PDF download & parsing
- Læser data/funds.csv (isin,source_url)
- Downloader PDF (requests m. UA/Referer)
- Ekstraherer tekst (pdfminer) fra BytesIO-stream
- Finder "Indre værdi" (NAV) og "Indre værdi dato" med defensiv heuristik (kig også på næste linje)
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

        # Hvis vi forventer tal/dato på næste linje
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

        # NAV-linje (varianter)
        if ("indre værdi" in low) or ("indrevaerdi" in low) or ("indreværdi" in low):
            after = ln.split(":", 1)[1] if ":" in ln else ln
            # fjern ord/valuta
            junk = ["DKK", "kr", "Kurs", "kurs", "Indre", "indre", "værdi", "værdi:", "værdi.", "værdi,"]
            for j in junk:
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
                want_nav_next = True

        # Dato-linje (varianter)
        if ("indre værdi dato" in low) or ("indre vaerdi dato" in low) or ("indreværdi dato" in low):
            after = ln.split(":", 1)[1].strip() if ":" in ln else ""
            iso = parse_date_to_iso(after)
            if iso:
                nav_date_iso = iso
            else:
                want_date_next = True

        if nav_val is not None and nav_date_iso is not None:
            break

    return nav_val, nav_date_iso

def parse_pdf_bytes(pdf_bytes: bytes) -> Tuple[Optional[float], Optional[str], str]:
    """Returner (nav, nav_date_iso, text_excerpt)"""
    with io.BytesIO(pdf_bytes) as f:
        text = extract_text(f) or ""
    nav, nav_date = extract_fields_from_text(text)
    return nav, nav_date, text[:4000]

# ---------- builders ----------

def build_latest(funds):
    rows = []
    for f in funds:
        isin = f["isin"]
        url = f["source_url"]
        resp = http_get(url)
        status = resp["status"]
        ct = resp["ct"] or ""
        ok = resp["ok"]
        content = resp["content"] if ok else None
        size = len(content) if content else 0

        print(f"[HTTP] {isin} -> ok={ok} status={status} ct={ct} size={size}")

        nav = None
        nav_date = None

        if ok and content:
            pdf_path = f"build/pdfs/{isin}.pdf"
            ensure_dir(pdf_path)
            try:
                with open(pdf_path, "wb") as pf:
                    pf.write(content)
            except Exception as e:
                print(f"[WARN] write PDF {isin}: {e}")

            try:
                nav, nav_date, excerpt = parse_pdf_bytes(content)
            except Exception as e:
                print(f"[WARN] pdfminer parse failed {isin}: {e}")
                excerpt = ""

            txt_path = f"build/text/{isin}.txt"
            ensure_dir(txt_path)
            try:
                with open(txt_path, "w", encoding="utf-8") as tf:
                    tf.write(excerpt)
            except Exception as e:
                print(f"[WARN] write TEXT {isin}: {e}")
        else:
            print(f"[WARN] GET failed {isin}: {resp['err']}")

        rows.append({
            "isin": isin,
            "nav": nav,
            "nav_date": nav_date,
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
    base_nav = 100.0
    rows = []
    for i, f in enumerate(funds):
        nav = base_nav + i * 0.37
        rows.append({
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
    return rows

# ---------- main ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="latest.json")
    ap.add_argument("--mock", action="store_true", help="generate mock latest.json")
    args = ap.parse_args()

    ensure_dir("build/pdfs/dummy.bin")
    ensure_dir("build/text/dummy.txt")

    funds = load_funds()
    print(f"[INFO] Loaded {len(funds)} funds from data/funds.csv")
    if not funds:
        print("[ERROR] No funds to process – check data/funds.csv")

    if args.mock:
        rows = build_mock_latest(funds)
    else:
        rows = build_latest(funds)

    payload = {"rows": rows, "run_date": date.today().isoformat()}
    out_path = os.path.abspath(args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    if not os.path.exists(out_path):
        raise RuntimeError(f"latest.json was not written at {out_path}")

    print(f"[OK] Wrote {out_path} with {len(rows)} rows")

if __name__ == "__main__":
    main()
