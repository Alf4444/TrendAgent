# parser/pfa.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import re
from typing import Dict, Optional, List
from datetime import datetime

LABELS_EXPECTED = [
    "Opstart",
    "Valuta",
    "Type",
    "Indre værdi",
    "Indre værdi dato",
    "Bæredygtighed",
]

# Tillad forskellige dashes
DASH_CHARS = "\u002d\u2010\u2011\u2012\u2013\u2014\u2212"  # - ‐ ‑ ‒ – — −


def _strip_colon_and_ws(s: str) -> str:
    # Normaliser spaces, NBSP og trailing kolon
    s = s.replace("\u00A0", " ")  # NBSP → space
    s = s.strip()
    s = s[:-1] if s.endswith(":") else s
    return re.sub(r"\s+", " ", s)


def _compact_lines(text: str) -> List[str]:
    out = []
    for line in text.splitlines():
        l = _strip_colon_and_ws(line)
        if l != "":
            out.append(l)
    return out


def _eq_label(a: str, b: str) -> bool:
    return _strip_colon_and_ws(a).lower() == _strip_colon_and_ws(b).lower()


def _find_label_block(lines: List[str]) -> Optional[int]:
    """
    Finder startindex hvor hele LABELS_EXPECTED forekommer i rækkefølge.
    """
    n = len(lines)
    L = LABELS_EXPECTED
    m = len(L)
    for i in range(n - m + 1):
        ok = True
        for j in range(m):
            if not _eq_label(lines[i + j], L[j]):
                ok = False
                break
        if ok:
            return i
    return None


def _extract_by_block(text: str) -> Optional[Dict[str, str]]:
    """
    Strategi A: Match label-blok (6 labels) efterfulgt af 6 værdilinjer (1:1).
    """
    lines = _compact_lines(text)
    i = _find_label_block(lines)
    if i is None:
        return None
    j = i + len(LABELS_EXPECTED)
    if j + len(LABELS_EXPECTED) > len(lines):
        return None
    values = lines[j : j + len(LABELS_EXPECTED)]
    return dict(zip(LABELS_EXPECTED, values))


def _extract_by_regex(text: str) -> Dict[str, Optional[str]]:
    """
    Strategi B (fallback): Regex efter 'Indre værdi' og 'Indre værdi dato'.
    Returnerer kun disse to (andre = None).
    """
    # Tillad at tal står på samme linje eller direkte på næste linje
    nav_txt = None
    lines = text.splitlines()
    for idx, ln in enumerate(lines):
        if re.search(r"^\s*Indre\s+værdi\s*:?\s*$", ln, flags=re.IGNORECASE):
            if idx + 1 < len(lines):
                nav_txt = _strip_colon_and_ws(lines[idx + 1])
            break
        m = re.search(r"Indre\s+værdi\s*:?\s*([0-9 .,\-]+)", ln, flags=re.IGNORECASE)
        if m:
            nav_txt = _strip_colon_and_ws(m.group(1))
            break

    date_txt = None
    for idx, ln in enumerate(lines):
        if re.search(r"^\s*Indre\s+værdi\s+dato\s*:?\s*$", ln, flags=re.IGNORECASE):
            if idx + 1 < len(lines):
                date_txt = _strip_colon_and_ws(lines[idx + 1])
            break
        m = re.search(
            r"Indre\s+værdi\s+dato\s*:?\s*([0-9\s" + re.escape(DASH_CHARS) + r"./]+)",
            ln,
            flags=re.IGNORECASE,
        )
        if m:
            date_txt = _strip_colon_and_ws(m.group(1))
            break

    return {
        "Opstart": None,
        "Valuta": None,
        "Type": None,
        "Indre værdi": nav_txt,
        "Indre værdi dato": date_txt,
        "Bæredygtighed": None,
    }


def _norm_number_danish(raw: str) -> Optional[float]:
    """
    Dansk tal: '1.234,56' → 1234.56 (float)
    """
    if not raw:
        return None
    s = raw.strip().replace(" ", "").replace("\u00A0", "")
    s = s.replace(".", "")  # tusindtalsprik
    s = s.replace(",", ".")  # decimal
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", s):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _norm_date_to_iso(raw: str) -> Optional[str]:
    """
    Konverterer dd-mm-yyyy (tillader ., /, og alle dash-varianter + omgivende spaces) → yyyy-mm-dd.
    """
    if not raw:
        return None
    s = raw.strip().replace("\u00A0", " ")
    # Normaliser separator til '-'
    for ch in ["/", "."] + list(DASH_CHARS):
        s = s.replace(ch, "-")
    s = re.sub(r"\s*-\s*", "-", s)  # fjern spaces omkring '-'
    s = re.sub(r"\s+", " ", s).strip()
    m = re.search(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b", s)
    if not m:
        return None
    dd, mm, yyyy = map(int, m.groups())
    try:
        dt = datetime(year=yyyy, month=mm, day=dd)
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def extract_stamdata(text: str) -> Dict[str, Optional[str]]:
    """
    Hovedfunktion: Prøv blok-match først, else regex fallback.
    """
    data = _extract_by_block(text)
    if data is None:
        data = _extract_by_regex(text)
    return data


def parse_pfa_from_text(isin: str, text: str) -> Dict[str, Optional[str]]:
    """
    Output pr. ISIN:
      - isin
      - nav_raw (string)       # original tekst
      - nav (float)            # normaliseret
      - nav_date_raw (string)  # original dato tekst
      - nav_date (ISO yyyy-mm-dd)
      - currency (hvis tilgængelig)
      - stamdata_raw (alle rå felter)
    """
    sd = extract_stamdata(text)

    nav_raw = sd.get("Indre værdi")
    nav = _norm_number_danish(nav_raw) if nav_raw else None

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
