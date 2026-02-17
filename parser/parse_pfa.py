# parser/parse_pfa.py
"""
TrendAgent - PDF download & parsing

- Læser data/funds.csv (isin,source_url)
- Downloader PDF (requests m. UA/Referer; retry/backoff)
- Ekstraherer tekst (pdfminer) fra BytesIO-stream
- Finder "Indre værdi" (NAV) og "Indre værdi dato" via robust heuristik:
    * 'Stamdata'-blok: etiketter i én kolonne, værdier efterfølgende linjer
      (vi inkluderer "Bæredygtighed" som sidste label for korrekt anker)
    * Fallback: rullende vindue (op til +12 linjer) med flere nøgleord (NAV/Kurs)
- Logger kort parse-resultat pr. ISIN
- Gemmer parse-debug (PDF + tekstuddrag)
- Understøtter --mock
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
from pdfminer.high_level import extract_text

UA = "TrendAgent/1.0 (+https://github.com/)"
HEADERS = {
    "User-Agent": UA,
    "Accept": "application/pdf,*/*;q=0.8",
    "Referer": "https://www.pfa.dk/",
}

# ---------- utils ----------

def ensure_dir(path: str) -> None:
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
    """
    1) Find 'Stamdata'-blok og par etiketter -> værdier.
       Vi inkluderer 'Bæredygtighed' som sidste label, fordi værdikolonnen starter
       LIGE efter den linje i dine factsheets. (Se parse-debug eksempler.) 
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
    n = len(lines)
    lower = [ln.lower() for ln in lines]

    # --- 1) Find 'Stamdata'-blok ---
    start_idx: Optional[int] = None
    for i, low in enumerate(lower):
        if "stamdata" in low:
            start_idx = i
            break
        # alternativ start: hvis vi indenfor 8 linjer ser både indre værdi og dato
        window = " ".join(lower[i:i + 8])
        if ("indre værdi" in window or "indrevaerdi" in window or "indreværdi" in window or "nav" in window or "kurs" in window) and \
           ("indre værdi dato" in window or "indre vaerdi dato" in window or "indreværdi dato" in window):
            start_idx = i
            break

    end_idx: Optional[int] = None
    if start_idx is not None:
        for j in range(start_idx + 1, n):
            low = lower[j]
            # heuristik for sektion-skift (overskrifter i dine ark)
            if low in ("afkast", "omkostninger", "risiko", "risikoklasse", "afdeling"):
                end_idx = j
                break
        if end_idx is None:
            end_idx = min(n, start_idx + 80)

    # --- 2) Parringslogik i blokken ---
    if start_idx is not None and end_idx is not None and end_idx > start_idx + 1:
        block = lines[start_idx:end_idx]
        block_low = [b.lower() for b in block]

        labels: List[Tuple[int, str]] = []
        # *** VIGTIGT: 'bæredygtighed' med som sidste label-anker ***
        label_keys = [
            ("opstart", "opstart"),
            ("valuta", "valuta"),
            ("type", "type"),
            ("indre værdi", "indre værdi"),
            ("indrevaerdi", "indre værdi"),
            ("indreværdi", "indre værdi"),
            ("nav", "indre værdi"),
            ("kurs", "indre værdi"),
            ("indre værdi dato", "indre værdi dato"),
            ("indre vaerdi dato", "indre værdi dato"),
            ("indreværdi dato", "indre værdi dato"),
            ("bæredygtighed", "bæredygtighed"),
            ("baeredygtighed", "bæredygtighed"),
        ]
        for idx, low in enumerate(block_low):
            for key, norm in label_keys:
                if key in low:
                    labels.append((idx, norm))
                    break

        if labels:
            last_label_idx = max(i for i, _ in labels)
            # værdierne begynder lige efter sidste label (inkl. 'Bæredygtighed')
            value_lines = block[last_label_idx + 1:]
            # byg label->value i rækkefølgen labels blev fundet
            pairs: Dict[str, str] = {}
            for k, (lbl_idx, norm) in enumerate(labels):
                if k < len(value_lines):
                    pairs.setdefault(norm, value_lines[k])

            # NAV
            nav_source = pairs.get("indre værdi")
            if nav_source:
                nav_candidate = first_number_candidate(clean_value_string(nav_source))
                if nav_candidate is not None:
                    nav_val = nav_candidate

            # DATO
            date_source = pairs.get("indre værdi dato")
            if date_source:
                date_candidate = first_date_candidate(date_source)
                if date_candidate:
                    nav_date_iso = date_candidate

            if nav_val is not None and nav_date_iso is not None:
                return nav_val, nav_date_iso

    # --- 3) Fallback: rullende vindue (op til +12 linjer) ---
    nav_keys = ("indre værdi", "indrevaerdi", "indreværdi", "nav", "kurs")
    date_keys = ("indre værdi dato", "indre vaerdi dato", "indreværdi dato")
    for i in range(n):
        if any(k in lower[i] for k in nav_keys):
            window = " ".join(lines[i:i + 12])
            nav_candidate = first_number_candidate(clean_value_string(window))
            if nav_candidate is not None and nav_val is None:
                nav_val = nav_candidate
        if any(k in lower[i] for k in date_keys):
            window = " ".join(lines[i:i + 12])
            date_candidate = first_date_candidate(window)
            if date_candidate and nav_date_iso is None:
                nav_date_iso = date_candidate
        if nav_val is not None and nav_date_iso is not None:
            break

    return nav_val, nav_date_iso

def parse_pdf_bytes(pdf_bytes: bytes) -> Tuple[Optional[float], Optional[str], str]:
    with io.BytesIO(pdf_bytes) as f:
        text = extract_text(f) or ""
    nav, nav_date = extract_fields_from_text(text)
    return nav, nav_date, text[:4000]

# ---------- builders ----------

def build_latest(funds: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
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

        nav: Optional[float] = None
        nav_date: Optional[str] = None

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

        print(f"[PARSE] {isin}: NAV={nav} NAV_DATE={nav_date}")

        rows.append({
            "isin": isin,
            "nav": nav,
            "nav_date": nav_date,
            # øvrige felter (udfyldes senere i modellen)
            "change_pct": None,
            "trend_shift": False,
            "cross_20_50": False,
            "trend_state": "NEUTRAL",
            "week_change_pct": None,
            "ytd_return": None,
            "drawdown": None,
        })
    return rows

def build_mock_latest(funds: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    base_nav = 100.0
    res: List[Dict[str, Any]] = []
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

# ---------- main ----------

def main() -> None:
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
