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
SPACE_CHARS = "\u00A0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u202F"  # NBSP/tynde mellemrum

LABELS_EXPECTED = [
    "Opstart",
    "Valuta",
    "Type",
    "Indre værdi",
    "Indre værdi dato",
    "Bæredygtighed",
]

# Tal (tillad tusindtals-separatorer og både komma/punktum decimal)
NUM_RX = re.compile(r"(?<!\d)(\d{1,3}(?:[ .\u00A0]\d{3})*(?:[.,]\d+)?|\d+[.,]\d+)(?!\d)")

# Dato dd[-./]mm[-./]yyyy (tillad spaces og alle dash-varianter)
DATE_RX = re.compile(
    r"\b(\d{1,2})\s*[-./" + re.escape(DASH_CHARS) + r"]\s*(\d{1,2})\s*[-./" + re.escape(DASH_CHARS) + r"]\s*(\d{4})\b"
)

# --------------------------
# Hjælpere
# --------------------------

def _normalize_text(s: str) -> str:
    """Ensart PDF-tekst: NFKC, fjern form feeds, NBSP→space, dashes→'-', trim højre."""
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
    """Fjern valuta/bogstaver, håndter tusindtals-separatorer og komma/punktum-decimal."""
    if not raw:
        return None
    s = re.sub(r"[^0-9\.,\s]", "", raw.strip())
    s = re.sub(r"\s+", "", s)
    if s == "":
        return None
    if "." in s and "," in s:
        # dk-format: '.' tusind, ',' decimal
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    # nu skal det ligne et float
    if not re.fullmatch(r"[+-]?\d+(\.\d+)?", s):
        return None
    try:
        return float(s)
    except ValueError:
        return None

def _norm_date_to_iso(raw: str) -> Optional[str]:
    """dd-mm-yyyy (og '.', '/', en-dash) → yyyy-mm-dd"""
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
# Strategi B: Label‑nabolag (samme linje + op til 4 linjer frem)
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

def _find_value_window(lines: List[str], start_idx: int, want_date: bool, lookahead: int = 4) -> Optional[str]:
    for k in range(start_idx, min(start_idx + lookahead + 1, len(lines))):
        ln = lines[k]
        if want_date:
            md = DATE_RX.search(ln)
