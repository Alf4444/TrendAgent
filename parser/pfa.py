# parser/pfa.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import re
import unicodedata
from typing import Dict, Optional, List
from datetime import datetime

__all__ = ["extract_stamdata", "parse_pfa_from_text"]

# --------------------------
# Normalisering & konstanter
# --------------------------

DASH_CHARS = "\u002d\u2010\u2011\u2012\u2013\u2014\u2212"  # - ‐ ‑ ‒ – — −
SPACE_CHARS = "\u00A0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u202F"  # NBSP + thin spaces

LABELS_EXPECTED = [
    "Opstart",
    "Valuta",
    "Type",
    "Indre værdi",
    "Indre værdi dato",
    "Bæredygtighed",
]

# Tal (tillad tusindtals‑separatorer og både komma/punktum decimal)
NUM_RX = re.compile(r"(?<!\d)(\d{1,3}(?:[ .\u00A0]\d{3})*(?:[.,]\d+)?|\d+[.,]\d+)(?!\d)")

# Dato dd[-./]mm[-./]yyyy (tillad spaces og alle dash‑varianter)
DATE_RX = re.compile(
    r"\b(\d{1,2})\s*[-./" + re.escape(DASH_CHARS) + r"]\s*(\d{1,2})\s*[-./" + re.escape(DASH_CHARS) + r"]\s*(\d{4})\b"
)

# --------------------------
# Hjælpere
# --------------------------

def _normalize_text(s: str) -> str:
    """Ensart PDF‑tekst: NFKC, fjern form feeds, NBSP→space, dashes→'-', trim højre."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\x0c", "\n")  # form feed → newline
    for ch in SPACE_CHARS:
        s = s.replace(ch, " ")
    for ch in DASH_CHARS:
        s = s.replace(ch, "-")
    return "\n".join(ln.rstrip() for ln in s.splitlines())

def _split_nonempty_lines(text: str) -> List[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip() != ""]

def _eq_label(a: str, b: str) -> bool:
    return a.strip().rstrip(":").lower() == b.strip().rstrip(":").lower()

def _norm_number_auto(raw: str) -> Optional[float]:
    """Fjern valuta/bogstaver, håndter tusindtals‑separatorer og komma/punktum‑decimal."""
    if not raw:
        return None
    s = re.sub(r"[^0-9\.,\s]", "", raw.strip())
    s = re.sub(r"\s+", "", s)
    if s == "":
        return None
    if "." in s and "," in s:
        # dk‑format: '.' tusind, ',' decimal
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", s):
        return None
    try:
        return float(s)
    except ValueError:
        return None

def _norm_date_to_iso(raw: str) -> Optional[str]:
    """dd‑mm‑yyyy (og '.', '/', en‑dash) → yyyy‑mm‑dd"""
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"[./]", "-", s)
    s = re.sub(r"\s*-\s*", "-", s)
    m = re.search(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b", s)
    if not m:
        m = DATE_RX.search(raw)
        if not m:
            return None
        dd, mm, yyyy = m.groups()
    else:
        dd, mm, yyyy = m.groups()
    try:
        return datetime(int(yyyy), int(mm), int(dd)).strftime("%Y-%m-%d")
    except ValueError:
        return None

# --------------------------
# Strategi A: 6 labels → 6 værdilinjer (happy path)
# --------------------------

def _find_label_block(lines: List[str]) -> Optional[int]:
    n, m = len(lines), len(LABELS_EXPECTED)
    for i in range(n - m + 1):
        ok = True
        for j in range(m):
            if not _eq_label(lines[i + j], LABELS_EXPECTED[j]):
                ok = False
                break
        if ok:
            return i
    return None

def _extract_by_block(text: str) -> Optional[Dict[str, str]]:
    lines = _split_nonempty_lines(text)
    i = _find_label_block(lines)
    if i is None:
        return None
    j = i + len(LABELS_EXPECTED)
    if j + len(LABELS_EXPECTED) > len(lines):
        return None
    values = lines[j : j + len(LABELS_EXPECTED)]
    return dict(zip(LABELS_EXPECTED, values))

# --------------------------
# Strategi B: Label‑nabolag (samme linje + op til 12 linjer frem)
# --------------------------

_NAV_LABELS = [
    re.compile(r"\bIndre\s+værdi(?:\s*\(NAV\))?\b", re.IGNORECASE),
    re.compile(r"\bIndre\s+værdi\s*pr\.\s*(?:bevis|andel)\b", re.IGNORECASE),
]
_DATE_LABELS = [
    re.compile(r"\bIndre\s+værdi\s+dato\b", re.IGNORECASE),
    re.compile(r"\bIndre\s+værdi\s*-\s*dato\b", re.IGNORECASE),
]

def _find_value_same_line(line: str, label_patterns: List[re.Pattern], want_date: bool) -> Optional[str]:
    for rx in label_patterns:
        m = rx.search(line)
        if not m:
            continue
        tail = line[m.end():].strip(" :-\t")
        if want_date:
            md = DATE_RX.search(tail)
            if md:
                dd, mm, yyyy = md.groups()
                return f"{dd}-{mm}-{yyyy}"
        else:
            mn = NUM_RX.search(tail)
            if mn:
                return mn.group(1)
    return None

def _find_value_window(lines: List[str], start_idx: int, want_date: bool, lookahead: int = 12) -> Optional[str]:
    for k in range(start_idx, min(start_idx + lookahead + 1, len(lines))):
        ln = lines[k]
        if want_date:
            md = DATE_RX.search(ln)
            if md:
                dd, mm, yyyy = md.groups()
                return f"{dd}-{mm}-{yyyy}"
        else:
            mn = NUM_RX.search(ln)
            if mn:
                return mn.group(1)
    return None

def _extract_by_window(text: str) -> Dict[str, Optional[str]]:
    lines = _split_nonempty_lines(text)
    nav_txt, date_txt = None, None

    # 1) Samme linje som label?
    for ln in lines:
        if nav_txt is None:
            nav_txt = _find_value_same_line(ln, _NAV_LABELS, want_date=False)
        if date_txt is None:
            date_txt = _find_value_same_line(ln, _DATE_LABELS, want_date=True)
        if nav_txt is not None and date_txt is not None:
            break

    # 2) Ellers: find label-linjen og kig 0..12 linjer frem
    if nav_txt is None:
        for idx, ln in enumerate(lines):
            if any(rx.search(ln) for rx in _NAV_LABELS):
                nav_txt = _find_value_window(lines, idx, want_date=False, lookahead=12)
                if nav_txt:
                    break
    if date_txt is None:
        for idx, ln in enumerate(lines):
            if any(rx.search(ln) for rx in _DATE_LABELS):
                date_txt = _find_value_window(lines, idx, want_date=True, lookahead=12)
                if date_txt:
                    break

    return {
        "Opstart": None,
        "Valuta": None,
        "Type": None,
        "Indre værdi": nav_txt,
        "Indre værdi dato": date_txt,
        "Bæredygtighed": None,
    }

# --------------------------
# Strategi C: Snæver fallback omkring "Stamdata"
# --------------------------

def _extract_near_stamdata(text: str) -> Dict[str, Optional[str]]:
    """
    Hvis hverken A eller B finder noget, kig i et lille udsnit efter ordet 'Stamdata'
    og fang første tal og første dato i det udsnit.
    """
    nav_txt, date_txt = None, None
    m = re.search(r"Stamdata", text, flags=re.IGNORECASE)
    if not m:
        return {"Opstart": None, "Valuta": None, "Type": None,
                "Indre værdi": None, "Indre værdi dato": None, "Bæredygtighed": None}

    window = text[m.end(): m.end() + 1500]  # kort udsnit efter 'Stamdata'
    mn = NUM_RX.search(window)
    if mn:
        nav_txt = mn.group(1)
    md = DATE_RX.search(window)
    if md:
        dd, mm, yyyy = md.groups()
        date_txt = f"{dd}-{mm}-{yyyy}"

    return {
        "Opstart": None,
        "Valuta": None,
        "Type": None,
        "Indre værdi": nav_txt,
        "Indre værdi dato": date_txt,
        "Bæredygtighed": None,
    }

# --------------------------
# Public API
# --------------------------

def extract_stamdata(raw_text: str) -> Dict[str, Optional[str]]:
    """Prøv A) blok, ellers B) label‑nabolag (udvidet vindue), ellers C) 'Stamdata'-nær fallback."""
    text = _normalize_text(raw_text or "")

    data = _extract_by_block(text)
    if data:
        return data

    data = _extract_by_window(text)
    if data.get("Indre værdi") is None and data.get("Indre værdi dato") is None:
        data = _extract_near_stamdata(text)

    return data

def parse_pfa_from_text(isin: str, text: str) -> Dict[str, Optional[str]]:
    """
    Output pr. ISIN (bruges af parser/main.py):
      - isin
      - nav_raw / nav (float)
      - nav_date_raw / nav_date (ISO yyyy-mm-dd)
      - currency (hvis tilgængelig)
      - stamdata_raw (alle rå felter)
    """
    sd = extract_stamdata(text or "")

    nav_raw = sd.get("Indre værdi")
    nav = _norm_number_auto(nav_raw) if nav_raw else None

    date_raw = sd.get("Indre værdi dato")
    nav_date = _norm_date_to_iso(date_raw) if date_raw else None

    currency = sd.get("Valuta")

    return {
        "isin": isin,
        "nav_raw": nav_raw,
        "nav": nav,
        "nav_date_raw": date_raw,
        "nav_date": nav_date,
        "currency": currency,
        "stamdata_raw": sd,
    }
