# parser/pfa.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import re
import unicodedata
from typing import Dict, Optional, List
from datetime import datetime

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

# Tal (både dansk og engelsk decimal) – vi tillader tusindtalsmellemrum/prikker
NUM_RX = re.compile(r"(?<!\d)(\d{1,3}(?:[ .\u00A0]\d{3})*(?:[.,]\d+)?|\d+[.,]\d+)(?!\d)")

# Dato dd[-./]mm[-./]yyyy (tolererer spaces og en/em‑dash)
DATE_RX = re.compile(
    r"\b(\d{1,2})\s*[-./" + re.escape(DASH_CHARS) + r"]\s*(\d{1,2})\s*[-./" + re.escape(DASH_CHARS) + r"]\s*(\d{4})\b"
)

def _normalize_text(s: str) -> str:
    """Ensartet tekst fra PDF → mere robust parsing."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\x0c", "\n")  # form feed → ny linje
    for ch in SPACE_CHARS:
        s = s.replace(ch, " ")
    for ch in DASH_CHARS:
        s = s.replace(ch, "-")
    # trim højre for hver linje
    return "\n".join([ln.rstrip() for ln in s.splitlines()])

def _split_nonempty_lines(text: str) -> List[str]:
    out = []
    for ln in text.splitlines():
        l = ln.strip()
        if l != "":
            out.append(l)
    return out

def _norm_number_auto(raw: str) -> Optional[float]:
    """
    Robust tal-normalisering:
      - fjerner valuta/bogstaver
      - fjerner tusindtalsseparatorer ('.', ' ' og NBSP)
      - håndterer både komma- og punktum-decimal
    """
    if not raw:
        return None
    s = re.sub(r"[^0-9\.,\s]", "", raw.strip())
    s = re.sub(r"\s+", "", s)
    if s == "":
        return None

    # Hvis både '.' og ',' forekommer → antag dansk (',' decimal)
    if "." in s and "," in s:
        s = s.replace(".", "")
        s = s.replace(",", ".")
    else:
        # Kun komma → dansk decimal
        if "," in s and "." not in s:
            s = s.replace(",", ".")
        # Kun punktum → engelsk decimal (ingen ændring)

    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", s):
        return None
    try:
        return float(s)
    except ValueError:
        return None

def _norm_date_to_iso(raw: str) -> Optional[str]:
    """
    dd-mm-yyyy (tillader '.', '/', en/em-dash + spaces) → yyyy-mm-dd
    """
    if not raw:
        return None
    s = raw.strip()
    s = re.sub(r"[./]", "-", s)
    s = re.sub(r"\s*-\s*", "-", s)
    m = re.search(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b", s)
    if not m:
        # sidste chance: find via DATE_RX direkte i rå-strengen
        m = DATE_RX.search(raw)
        if not m:
            return None
        dd, mm, yyyy = m.groups()
    else:
        dd, mm, yyyy = m.groups()
    try:
        dt = datetime(year=int(yyyy), month=int(mm), day=int(dd))
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None

# --------------------------
# Strategi A: 6 labels → 6 værdilinjer
# --------------------------

def _eq_label(a: str, b: str) -> bool:
    return a.strip().rstrip(":").lower() == b.strip().rstrip(":").lower()

def _find_label_block(lines: List[str]) -> Optional[int]:
    n = len(lines)
    m = len(LABELS_EXPECTED)
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
# Strategi B: Label og værdi på SAMME linje (to‑kolonne tabel)
# + fallback vindue 0..5 linjer frem
# --------------------------

def _find_value_same_line(line: str, label_patterns: List[re.Pattern], want_date: bool) -> Optional[str]:
    """
    Forsøg at finde værdi på samme linje som label, fx:
      "Indre værdi: 202,69"  eller  "Indre værdi dato 17-02-2026"
    """
    for rx in label_patterns:
        m = rx.search(line)
        if m:
            tail = line[m.end():].strip(" :-–—\t")
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

def _find_value_next_lines(lines: List[str], start_idx: int, want_date: bool, lookahead: int = 6) -> Optional[str]:
    """
    Kig i samme linje og de efterfølgende lookahead-linjer efter første tal/dato.
    """
    for k in range(start_idx, min(start_idx + lookahead + 1, len(lines))):
        ln = lines[k]
        if want_date:
            md = DATE_RX.search(ln)
            if md:
                dd, mm, yyyy = md.groups()
                return f"{dd}-{mm}-{yyyy}"
        else:
