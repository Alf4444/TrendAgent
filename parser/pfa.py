# parser/pfa.py
# -*- coding: utf-8 -*-

from __future__ import annotations
import re
import unicodedata
from typing import Dict, Optional, List, Tuple
from datetime import datetime

# ----------------------------------------
# KONSTANTER / REGEX
# ----------------------------------------

DASH_CHARS = "\u002d\u2010\u2011\u2012\u2013\u2014\u2212"  # - ‐ ‑ ‒ – — −
SPACE_CHARS = "\u00A0\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u202F"  # NBSP + thin spaces

NAV_LABELS = [
    r"Indre\s+værdi(?:\s*\(NAV\))?",
    r"Indre\s+værdi\s*pr\.\s*(?:bevis|andel)",
]
DATE_LABELS = [
    r"Indre\s+værdi[\s" + DASH_CHARS + r"]*dato",
]

# fx "1.234,56" eller "202.69" eller "381,13 DKK"
NUMBER_CORE = r"[0-9][0-9\s\.\," + SPACE_CHARS + r"]*[0-9](?:,[0-9]+|\.[0-9]+)?"
DATE_CORE = r"[0-9]{1,2}\s*[-./]\s*[0-9]{1,2}\s*[-./]\s*[0-9]{4}"

# ----------------------------------------
# HJÆLPERE
# ----------------------------------------

def _normalize_text(text: str) -> str:
    """
    Normaliser PDF-tekst for robust parsing:
    - NFKC normalisering (ensartede unicode-tegn)
    - Fjern form feeds
    - Erstat NBSP/thin space med normal space
    - Ensret alle slags dashes til '-'
    - Trim trailing spaces pr. linje
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = s.replace("\x0c", "\n")  # form feed → newline
    for ch in SPACE_CHARS:
        s = s.replace(ch, " ")
    for ch in DASH_CHARS:
        s = s.replace(ch, "-")
    # Normaliser linjeskift og trim
    lines = [ln.rstrip() for ln in s.splitlines()]
    return "\n".join(lines)


def _split_nonempty_lines(text: str) -> List[str]:
    out = []
    for ln in text.splitlines():
        l = ln.strip()
        if l != "":
            out.append(l)
    return out


def _norm_date_to_iso(raw: str) -> Optional[str]:
    """
    dd-mm-yyyy (også med '.' eller '/'), tolerer spaces.
    Returnerer ISO yyyy-mm-dd eller None.
    """
    if not raw:
        return None
    s = raw.strip()
    # Erstat varianter til '-'
    s = re.sub(r"[./]", "-", s)
    s = re.sub(r"\s*-\s*", "-", s)
    m = re.search(r"\b(\d{1,2})-(\d{1,2})-(\d{4})\b", s)
    if not m:
        return None
    dd, mm, yyyy = map(int, m.groups())
    try:
        dt = datetime(year=yyyy, month=mm, day=dd)
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def _norm_number_auto(raw: str) -> Optional[float]:
    """
    Tal-normalisering som automatisk detekterer decimaltegn.
    Eksempler:
      "141,68" -> 141.68
      "202.69" -> 202.69
      "1.234,56" -> 1234.56
      "381,13 DKK" -> 381.13
    """
    if not raw:
        return None
    s = raw.strip()
    # Fjern valuta/tekst omkring tal
    # Behold kun cifre, punktum, komma og mellemrum
    s = re.sub(r"[^0-9\.,\s]", "", s)
    # Fjern ekstra spaces
    s = re.sub(r"\s+", "", s)

    if s == "":
        return None

    # Hvis både '.' og ',' forekommer:
    #   antag dansk format: '.' tusinder, ',' decimal
    if "." in s and "," in s:
        s = s.replace(".", "")
        s = s.replace(",", ".")
    else:
        # Hvis kun komma → dansk decimal
        if "," in s and "." not in s:
            s = s.replace(",", ".")
        # Hvis kun punktum → engelsk decimal (lad den være)
        # Hvis ingen separator → heltal
        # (intet at gøre)

    # Gyldigt format nu?
